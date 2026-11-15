"""
Backend de Áudio do Windows + Sincronização com Discord + Leitura de Bateria HID (HyperX Cloud III Wireless).

Por que uma thread MTA dedicada (_COMWorker)?
O Qt roda a interface gráfica em uma thread STA (Single-Threaded Apartment). Chamar APIs COM de áudio
cross-process (como IPolicyConfig e Windows.Media.Internal.AudioPolicyConfig) diretamente de eventos de
mouse/timer na thread STA dispara a exceção 0x8001010d (RPC_E_CANTCALLOUT_ININPUTSYNCCALL).
Ao executar todas as chamadas COM de áudio dentro de uma thread MTA dedicada (COINIT_MULTITHREADED = 0),
a troca do Windows + Mixer do Discord ocorre instantaneamente e sem conflito com a fila de mensagens do Qt.
"""

from concurrent.futures import Future
import ctypes
from ctypes import wintypes
import glob
import json
import os
import queue
import re
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid

import comtypes
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

try:
    import hid
except ImportError:
    hid = None

# --- GUIDs e Constantes COM do Windows Core Audio ---
CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
CLSID_PolicyConfigClient = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
IID_IPolicyConfig = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
IID_IAudioEndpointVolume = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
IID_IAudioPolicyConfigFactory_Win11 = GUID("{AB3D4648-E242-459F-B02F-541C70306324}")
IID_IAudioPolicyConfigFactory_Win10 = GUID("{2A59116D-6C4F-45E0-A74F-707E3FEF9258}")

DEVINTERFACE_AUDIO_RENDER = "{e6327cad-dcec-4949-ae8a-991e976a79d2}"
DEVINTERFACE_AUDIO_CAPTURE = "{2eef81be-33fa-4800-9670-1cd474972c3f}"

eRender = 0
eCapture = 1
DEVICE_STATE_ACTIVE = 0x00000001
COINIT_MULTITHREADED = 0x0


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.WORD),
        ("r1", wintypes.WORD),
        ("r2", wintypes.WORD),
        ("r3", wintypes.WORD),
        ("val", ctypes.c_void_p),
        ("p2", ctypes.c_void_p),
    ]


PKEY_Device_FriendlyName = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
PKEY_Device_DeviceDesc = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 2)


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.DWORD), "cProps")),
        COMMETHOD(
            [],
            HRESULT,
            "GetAt",
            (["in"], wintypes.DWORD, "iProp"),
            (["out"], ctypes.POINTER(PROPERTYKEY), "pkey"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetValue",
            (["in"], ctypes.POINTER(PROPERTYKEY), "key"),
            (["out"], ctypes.POINTER(PROPVARIANT), "pv"),
        ),
    ]


class IAudioEndpointVolume(IUnknown):
    _iid_ = IID_IAudioEndpointVolume
    _methods_ = [
        COMMETHOD([], HRESULT, "RegisterControlChangeNotify", (["in"], ctypes.c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "UnregisterControlChangeNotify", (["in"], ctypes.c_void_p, "pNotify")),
        COMMETHOD([], HRESULT, "GetChannelCount", (["out"], ctypes.POINTER(wintypes.UINT), "pnChannelCount")),
        COMMETHOD(
            [],
            HRESULT,
            "SetMasterVolumeLevel",
            (["in"], ctypes.c_float, "fLevelDB"),
            (["in"], ctypes.POINTER(GUID), "pguidEventContext"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetMasterVolumeLevelScalar",
            (["in"], ctypes.c_float, "fLevel"),
            (["in"], ctypes.POINTER(GUID), "pguidEventContext"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetMasterVolumeLevel",
            (["out"], ctypes.POINTER(ctypes.c_float), "pfLevelDB"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetMasterVolumeLevelScalar",
            (["out"], ctypes.POINTER(ctypes.c_float), "pfLevel"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetChannelVolumeLevel",
            (["in"], wintypes.UINT, "nChannel"),
            (["in"], ctypes.c_float, "fLevelDB"),
            (["in"], ctypes.POINTER(GUID), "pguidEventContext"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetChannelVolumeLevelScalar",
            (["in"], wintypes.UINT, "nChannel"),
            (["in"], ctypes.c_float, "fLevel"),
            (["in"], ctypes.POINTER(GUID), "pguidEventContext"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetChannelVolumeLevel",
            (["in"], wintypes.UINT, "nChannel"),
            (["out"], ctypes.POINTER(ctypes.c_float), "pfLevelDB"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetChannelVolumeLevelScalar",
            (["in"], wintypes.UINT, "nChannel"),
            (["out"], ctypes.POINTER(ctypes.c_float), "pfLevel"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "SetMute",
            (["in"], wintypes.BOOL, "bMute"),
            (["in"], ctypes.POINTER(GUID), "pguidEventContext"),
        ),
        COMMETHOD([], HRESULT, "GetMute", (["out"], ctypes.POINTER(wintypes.BOOL), "pbMute")),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], ctypes.POINTER(GUID), "iid"),
            (["in"], wintypes.DWORD, "dwClsCtx"),
            (["in"], ctypes.c_void_p, "pActivationParams"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IUnknown)), "ppInterface"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OpenPropertyStore",
            (["in"], wintypes.DWORD, "stgmAccess"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IPropertyStore)), "ppProperties"),
        ),
        COMMETHOD([], HRESULT, "GetId", (["out"], ctypes.POINTER(wintypes.LPWSTR), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState", (["out"], ctypes.POINTER(wintypes.DWORD), "pdwState")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], ctypes.POINTER(wintypes.UINT), "pcDevices")),
        COMMETHOD(
            [],
            HRESULT,
            "Item",
            (["in"], wintypes.UINT, "nDevice"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "ppDevice"),
        ),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = IID_IMMDeviceEnumerator
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "EnumAudioEndpoints",
            (["in"], wintypes.UINT, "dataFlow"),
            (["in"], wintypes.DWORD, "dwStateMask"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)), "ppDevices"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], wintypes.UINT, "dataFlow"),
            (["in"], wintypes.UINT, "role"),
            (["out"], ctypes.POINTER(ctypes.POINTER(IMMDevice)), "ppEndpoint"),
        ),
    ]


class IPolicyConfig(IUnknown):
    _iid_ = IID_IPolicyConfig
    _methods_ = [
        COMMETHOD([], HRESULT, "GetMixFormat", (["in"], wintypes.LPCWSTR, "pwstrId"), (["out"], ctypes.POINTER(ctypes.c_void_p), "ppFormat")),
        COMMETHOD([], HRESULT, "GetDeviceFormat", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.INT, "bDefault"), (["out"], ctypes.POINTER(ctypes.c_void_p), "ppFormat")),
        COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], wintypes.LPCWSTR, "pwstrId")),
        COMMETHOD([], HRESULT, "SetDeviceFormat", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], ctypes.c_void_p, "pEndpointFormat"), (["in"], ctypes.c_void_p, "pMixFormat")),
        COMMETHOD([], HRESULT, "GetProcessingPeriod", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.INT, "bDefault"), (["out"], ctypes.POINTER(ctypes.c_longlong), "pmftDefaultPeriod"), (["out"], ctypes.POINTER(ctypes.c_longlong), "pmftMinimumPeriod")),
        COMMETHOD([], HRESULT, "SetProcessingPeriod", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], ctypes.POINTER(ctypes.c_longlong), "pmftPeriod")),
        COMMETHOD([], HRESULT, "GetShareMode", (["in"], wintypes.LPCWSTR, "pwstrId"), (["out"], ctypes.POINTER(ctypes.c_void_p), "pMode")),
        COMMETHOD([], HRESULT, "SetShareMode", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], ctypes.c_void_p, "mode")),
        COMMETHOD([], HRESULT, "GetPropertyValue", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.INT, "bFxStore"), (["in"], ctypes.c_void_p, "key"), (["out"], ctypes.c_void_p, "pv")),
        COMMETHOD([], HRESULT, "SetPropertyValue", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.INT, "bFxStore"), (["in"], ctypes.c_void_p, "key"), (["in"], ctypes.c_void_p, "pv")),
        COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.UINT, "role")),
        COMMETHOD([], HRESULT, "SetEndpointVisibility", (["in"], wintypes.LPCWSTR, "pwstrId"), (["in"], wintypes.INT, "bVisible")),
    ]


# --- Thread MTA dedicada para chamadas COM sem erro 0x8001010d ---
class _MTAWorker:
    def __init__(self):
        self._q = queue.Queue()
        self._t = threading.Thread(target=self._loop, daemon=True, name="AudioCOM_MTA")
        self._t.start()

    def _loop(self):
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        while True:
            fn, args, kwargs, fut = self._q.get()
            try:
                res = fn(*args, **kwargs)
                fut.set_result(res)
            except Exception as e:
                fut.set_exception(e)

    def call(self, fn, *args, timeout: float = 4.0, **kwargs):
        if threading.current_thread() is self._t:
            return fn(*args, **kwargs)
        fut = Future()
        self._q.put((fn, args, kwargs, fut))
        return fut.result(timeout=timeout)


_mta = _MTAWorker()


def guess_short_name_and_kind(full_name: str, flow: int = eRender):
    """Deduz um nome curto amigável e o ícone ideal para cada dispositivo de áudio."""
    low = full_name.lower()
    if flow == eCapture:
        if "solocast" in low:
            return "SoloCast", "microphone"
        if "cloud iii" in low or "cloud 3" in low:
            return "Mic Cloud III", "microphone"
        return full_name.split("(")[0].strip() or "Microfone", "microphone"

    if "cloud iii" in low or "cloud 3" in low:
        return "Cloud III", "headset"
    if "cloud ii" in low or "cloud 2" in low:
        return "Cloud II", "headset"
    if "cloud alpha" in low:
        return "Cloud Alpha", "headset"
    if "hyperx" in low:
        return "HyperX", "headset"
    if "kz" in low or "edx" in low or "iem" in low:
        return "KZ EDX Pro", "inear"
    if "g pro" in low or "pro x" in low:
        return "G PRO X", "headset"
    if "logitech" in low or "g733" in low or "g435" in low or "astro" in low:
        return "Logitech", "headset"
    if "razer" in low or "blackshark" in low or "kraken" in low:
        return "Razer", "headset"
    if "arctis" in low or "steelseries" in low:
        return "Arctis", "headset"
    if "corsair" in low or "virtuoso" in low or "hs80" in low:
        return "Corsair", "headset"
    if "high definition audio" in low and ("fones" in low or "headphone" in low):
        return "Fone P2", "inear"
    if "realtek" in low and ("fones" in low or "headphone" in low or "second output" in low):
        return "Fone P2", "inear"
    if "kg273" in low or "nvidia" in low or "amd high definition" in low or "displayport" in low or "hdmi" in low:
        if "(" in full_name:
            prefix = full_name.split("(")[0].strip()
            return prefix or "Monitor", "monitor"
        return "Monitor", "monitor"
    if "steam streaming" in low:
        return "Steam Audio", "speaker"
    if "alto-falante" in low or "speaker" in low:
        if "(" in full_name and ")" in full_name:
            inner = full_name.split("(", 1)[1].rsplit(")", 1)[0].strip()
            return inner[:18], "speaker"
        return "Alto-falantes", "speaker"
    if "fones" in low or "headset" in low or "headphone" in low:
        if "(" in full_name and ")" in full_name:
            inner = full_name.split("(", 1)[1].rsplit(")", 1)[0].strip()
            return inner[:18], "headset"
        return "Fones", "headset"
    return full_name[:18].strip(), "generic"


def is_virtual_noise_device(full_name: str) -> bool:
    low = full_name.lower()
    return "steam streaming" in low or "virtual audio" in low


def _read_prop_str(store, pkey) -> str:
    try:
        pv = store.GetValue(ctypes.byref(pkey))
        if pv.vt == 31 and pv.val:
            return ctypes.wstring_at(pv.val)
    except Exception:
        pass
    return ""


def _list_audio_devices_mta(flow: int = eRender):
    devices = []
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        try:
            def_console = enum.GetDefaultAudioEndpoint(flow, 0).GetId()
        except Exception:
            def_console = None
        try:
            def_comm = enum.GetDefaultAudioEndpoint(flow, 2).GetId()
        except Exception:
            def_comm = def_console

        coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
        count = coll.GetCount()
        for i in range(count):
            dev = coll.Item(i)
            did = dev.GetId()
            store = dev.OpenPropertyStore(0)
            full_name = _read_prop_str(store, PKEY_Device_FriendlyName) or did
            desc = _read_prop_str(store, PKEY_Device_DeviceDesc)

            vol_pct = None
            muted = False
            try:
                unk = dev.Activate(ctypes.byref(IID_IAudioEndpointVolume), 1, None)
                ep_vol = unk.QueryInterface(IAudioEndpointVolume)
                vol_pct = round(float(ep_vol.GetMasterVolumeLevelScalar()) * 100)
                muted = bool(ep_vol.GetMute())
            except Exception:
                pass

            short_name, kind = guess_short_name_and_kind(full_name, flow)
            devices.append(
                {
                    "id": did,
                    "full_name": full_name,
                    "desc": desc,
                    "default_short_name": short_name,
                    "default_kind": kind,
                    "is_default_console": (did == def_console),
                    "is_default_comm": (did == def_comm),
                    "volume": vol_pct,
                    "muted": muted,
                    "flow": flow,
                }
            )
    except Exception:
        pass
    return devices


def list_audio_devices(flow: int = eRender):
    try:
        return _mta.call(_list_audio_devices_mta, flow)
    except Exception:
        return []


def _set_device_volume_mta(device_id: str, volume_pct: int, flow: int = eRender) -> bool:
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            if dev.GetId() == device_id:
                unk = dev.Activate(ctypes.byref(IID_IAudioEndpointVolume), 1, None)
                ep_vol = unk.QueryInterface(IAudioEndpointVolume)
                scalar = max(0.0, min(1.0, volume_pct / 100.0))
                ep_vol.SetMasterVolumeLevelScalar(scalar, None)
                return True
    except Exception:
        pass
    return False


def set_device_volume(device_id: str, volume_pct: int, flow: int = eRender) -> bool:
    try:
        return bool(_mta.call(_set_device_volume_mta, device_id, volume_pct, flow))
    except Exception:
        return False


def _set_device_mute_mta(device_id: str, mute: bool, flow: int = eRender) -> bool:
    try:
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            if dev.GetId() == device_id:
                unk = dev.Activate(ctypes.byref(IID_IAudioEndpointVolume), 1, None)
                ep_vol = unk.QueryInterface(IAudioEndpointVolume)
                ep_vol.SetMute(1 if mute else 0, None)
                return True
    except Exception:
        pass
    return False


def set_device_mute(device_id: str, mute: bool, flow: int = eRender) -> bool:
    try:
        return bool(_mta.call(_set_device_mute_mta, device_id, mute, flow))
    except Exception:
        return False


# --- Sincronização de Áudio por Processo (Discord.exe) via IAudioPolicyConfigFactory ---
def _get_discord_pids() -> list[int]:
    """Encontra todos os PIDs ativos do Discord.exe sem abrir janela de console."""
    pids = []
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Discord.exe", "/FO", "CSV", "/NH"],
            startupinfo=si,
            creationflags=0x08000000,
            text=True,
            timeout=2.0,
        )
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == "discord.exe":
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
    except Exception:
        pass
    return pids


def _route_process_audio_to_endpoint_mta(pids: list[int], device_id: str, flow: int = eRender) -> bool:
    """
    Usa Windows.Media.Internal.AudioPolicyConfig (IAudioPolicyConfigFactory) na thread MTA para
    fixar o endpoint de saída de todos os processos do Discord.exe no Mixer de Volume do Windows.
    """
    if not pids:
        return False
    try:
        combase = ctypes.windll.combase
        WindowsCreateString = combase.WindowsCreateString
        WindowsCreateString.argtypes = [wintypes.LPCWSTR, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)]
        WindowsDeleteString = combase.WindowsDeleteString
        WindowsDeleteString.argtypes = [ctypes.c_void_p]
        RoGetActivationFactory = combase.RoGetActivationFactory
        RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]

        hs_class = ctypes.c_void_p()
        cls_name = "Windows.Media.Internal.AudioPolicyConfig"
        WindowsCreateString(cls_name, len(cls_name), ctypes.byref(hs_class))

        factory_ptr = ctypes.c_void_p()
        set_idx = 25
        hr = RoGetActivationFactory(
            hs_class, ctypes.byref(IID_IAudioPolicyConfigFactory_Win11), ctypes.byref(factory_ptr)
        )
        if hr != 0 or not factory_ptr.value:
            hr = RoGetActivationFactory(
                hs_class, ctypes.byref(IID_IAudioPolicyConfigFactory_Win10), ctypes.byref(factory_ptr)
            )
            set_idx = 21
        WindowsDeleteString(hs_class)

        if hr != 0 or not factory_ptr.value:
            return False

        vtable = ctypes.cast(factory_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        SetPersisted = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
        )(vtable[set_idx])

        iface_guid = DEVINTERFACE_AUDIO_RENDER if flow == eRender else DEVINTERFACE_AUDIO_CAPTURE
        full_dev_str = f"\\\\?\\SWD#MMDEVAPI#{device_id}#{iface_guid}"
        dev_hs = ctypes.c_void_p()
        WindowsCreateString(full_dev_str, len(full_dev_str), ctypes.byref(dev_hs))

        routed_any = False
        for pid in pids:
            for role in (0, 1, 2):
                # Mantém o endpoint persistido para o processo Discord.exe no Mixer do Windows
                res = SetPersisted(factory_ptr, pid, flow, role, dev_hs)
                if res == 0:
                    routed_any = True

        WindowsDeleteString(dev_hs)
        return routed_any
    except Exception:
        return False


# --- Integração Oficial via Discord Local RPC (\\.\pipe\discord-ipc-0) ---
def _ipc_send(pipe, opcode: int, payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    pipe.write(struct.pack("<II", opcode, len(raw)) + raw)


def _ipc_recv(pipe):
    hdr = pipe.read(8)
    if not hdr or len(hdr) < 8:
        return None, None
    op, length = struct.unpack("<II", hdr)
    data = pipe.read(length)
    return op, json.loads(data.decode("utf-8", errors="replace"))


def discord_rpc_set_output_device(device_id: str, client_id: str, access_token: str) -> tuple[bool, str]:
    r"""
    Altera diretamente a opção 'Dispositivo de Saída' dentro das configurações de Voz e Vídeo do Discord
    usando a API oficial Local RPC (comando SET_VOICE_SETTINGS em \\.\pipe\discord-ipc-0).
    """
    if not client_id or not access_token:
        return False, "Credenciais RPC não configuradas"

    for i in range(10):
        pipe_path = rf"\\.\pipe\discord-ipc-{i}"
        if not os.path.exists(pipe_path):
            continue
        try:
            with open(pipe_path, "r+b", buffering=0) as f:
                _ipc_send(f, 0, {"v": 1, "client_id": client_id})
                _, r_ready = _ipc_recv(f)
                if not r_ready or r_ready.get("evt") != "READY":
                    continue

                _ipc_send(
                    f,
                    1,
                    {
                        "cmd": "AUTHENTICATE",
                        "args": {"access_token": access_token},
                        "nonce": str(uuid.uuid4()),
                    },
                )
                _, r_auth = _ipc_recv(f)
                if not r_auth or r_auth.get("evt") == "ERROR":
                    msg = (r_auth or {}).get("data", {}).get("message", "Token inválido ou expirado")
                    return False, msg

                # Envia SET_VOICE_SETTINGS para mudar a saída dentro do Discord
                _ipc_send(
                    f,
                    1,
                    {
                        "cmd": "SET_VOICE_SETTINGS",
                        "args": {"output": {"device_id": device_id}},
                        "nonce": str(uuid.uuid4()),
                    },
                )
                _, r_set = _ipc_recv(f)
                if r_set and r_set.get("evt") != "ERROR":
                    return True, "OK"
                # Tenta também com o GUID curto caso o Discord espere sem prefixo
                short_guid = device_id.split(".")[-1] if "." in device_id else device_id
                _ipc_send(
                    f,
                    1,
                    {
                        "cmd": "SET_VOICE_SETTINGS",
                        "args": {"output": {"device_id": short_guid}},
                        "nonce": str(uuid.uuid4()),
                    },
                )
                _, r_set2 = _ipc_recv(f)
                if r_set2 and r_set2.get("evt") != "ERROR":
                    return True, "OK"
                return False, "Falha em SET_VOICE_SETTINGS"
        except Exception as e:
            return False, str(e)
    return False, "Discord não está aberto (pipe discord-ipc não encontrado)"


def discord_rpc_authorize(client_id: str, client_secret: str, redirect_uri: str = "http://127.0.0.1") -> tuple[bool, str]:
    r"""
    Abre o modal nativo de autorização dentro do próprio Discord via \\.\pipe\discord-ipc-0
    e troca o código por um access_token OAuth2 para controlar o dispositivo de voz do Discord.
    """
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        return False, "Preencha o Client ID e o Client Secret da aplicação Discord."

    for i in range(10):
        pipe_path = rf"\\.\pipe\discord-ipc-{i}"
        if not os.path.exists(pipe_path):
            continue
        try:
            with open(pipe_path, "r+b", buffering=0) as f:
                _ipc_send(f, 0, {"v": 1, "client_id": client_id})
                _, r_ready = _ipc_recv(f)
                if not r_ready or r_ready.get("evt") != "READY":
                    continue

                _ipc_send(
                    f,
                    1,
                    {
                        "cmd": "AUTHORIZE",
                        "args": {
                            "client_id": client_id,
                            "scopes": ["rpc", "rpc.voice.read", "rpc.voice.write"],
                        },
                        "nonce": str(uuid.uuid4()),
                    },
                )
                _, r_authz = _ipc_recv(f)
                if not r_authz or r_authz.get("evt") == "ERROR":
                    msg = (r_authz or {}).get("data", {}).get("message", "Autorização recusada no Discord")
                    return False, msg

                code = r_authz.get("data", {}).get("code")
                if not code:
                    return False, "Código de autorização não retornado pelo Discord."

                # Troca code por access_token na API OAuth2 do Discord
                body = urllib.parse.urlencode(
                    {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    "https://discord.com/api/v10/oauth2/token",
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": "AudioSwitchBT/1.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    tok_data = json.loads(resp.read().decode("utf-8"))
                access_token = tok_data.get("access_token")
                if access_token:
                    return True, access_token
                return False, "Token não encontrado na resposta."
        except Exception as e:
            return False, f"Erro ao autorizar: {e}"
    return False, "Discord não encontrado em execução."


def get_discord_configured_output_status() -> dict:
    """
    Inspeciona de forma somente-leitura o LevelDB do Discord (%APPDATA%\\discord\\Local Storage\\leveldb)
    para verificar se o 'Dispositivo de Saída' dentro do Discord está como 'default' ou travado em um fone fixo.
    """
    ldb_dir = os.path.expandvars(r"%APPDATA%\discord\Local Storage\leveldb")
    if not os.path.isdir(ldb_dir):
        return {"mode": "unknown", "raw": None}
    try:
        files = sorted(
            [p for p in glob.glob(os.path.join(ldb_dir, "*")) if p.endswith((".ldb", ".log"))],
            key=os.path.getmtime,
            reverse=True,
        )
        for p in files:
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            if b"MediaEngineStore" not in data:
                continue
            # Procura por outputDeviceId explícito ou pelo segundo GUID após inputDeviceId
            m_explicit = re.search(rb'outputDeviceId":"([^"]+)"', data)
            if m_explicit:
                val = m_explicit.group(1).decode("ascii", errors="ignore")
                return {"mode": "default" if val == "default" else "fixed", "device_id": val}

            idx = data.find(b"DeviceId")
            if idx != -1:
                window = data[max(0, idx - 60) : min(len(data), idx + 220)]
                if b'"default"' in window[40:]:
                    return {"mode": "default", "device_id": "default"}
                # Em blocos comprimidos por Snappy no LevelDB, o GUID de saída aparece parcialmente
                if b"9223595e" in window or b"95e-" in window or b"4833-815c" in window:
                    return {
                        "mode": "fixed",
                        "device_id": "{0.0.0.00000000}.{9223595e-7109-4833-815c-5863460660d9}",
                        "hint": "Fones de ouvido (HyperX Cloud III Wireless)",
                    }
                if b"2d60c3e0" in window or b"1bcd-48f5" in window:
                    return {
                        "mode": "fixed",
                        "device_id": "{0.0.0.00000000}.{2d60c3e0-1bcd-48f5-a51f-0f59c4bfd1b9}",
                        "hint": "KZ EDX Pro (High Definition Audio Device)",
                    }
    except Exception:
        pass
    return {"mode": "unknown", "device_id": None}


def _switch_audio_output_mta(
    device_id: str,
    sync_discord: bool = True,
    sync_comm: bool = True,
    linked_mic_id: str | None = None,
) -> bool:
    ok = False
    try:
        pc = comtypes.CoCreateInstance(CLSID_PolicyConfigClient, interface=IPolicyConfig)
        pc.SetDefaultEndpoint(device_id, 0)  # eConsole (Jogos, Sistema, Navegador)
        pc.SetDefaultEndpoint(device_id, 1)  # eMultimedia (Mídia)
        if sync_comm or sync_discord:
            pc.SetDefaultEndpoint(device_id, 2)  # eCommunications (Discord 'Default' / Voz)
        ok = True

        if linked_mic_id:
            for role in (0, 1, 2):
                pc.SetDefaultEndpoint(linked_mic_id, role)
    except Exception:
        pass

    if sync_discord:
        pids = _get_discord_pids()
        if pids:
            _route_process_audio_to_endpoint_mta(pids, device_id, eRender)

    return ok


def switch_audio_output(
    device_id: str,
    sync_discord: bool = True,
    sync_comm: bool = True,
    linked_mic_id: str | None = None,
    rpc_client_id: str = "",
    rpc_access_token: str = "",
) -> bool:
    """
    Executa a troca completa de áudio na thread MTA:
    1) Define Dispositivo Padrão (eConsole + eMultimedia) e Dispositivo de Comunicação Padrão (eCommunications)
    2) Redireciona todos os processos Discord.exe no Mixer de Volume do Windows (SetPersistedDefaultAudioEndpoint)
    3) Se o Discord RPC estiver autenticado, envia SET_VOICE_SETTINGS direto para o Discord via IPC
    """
    try:
        ok = bool(_mta.call(_switch_audio_output_mta, device_id, sync_discord, sync_comm, linked_mic_id))
    except Exception:
        ok = False

    if sync_discord and rpc_client_id and rpc_access_token:
        threading.Thread(
            target=discord_rpc_set_output_device,
            args=(device_id, rpc_client_id, rpc_access_token),
            daemon=True,
        ).start()

    return ok


# --- Leitura de Bateria HID para HyperX Cloud III Wireless ---
def read_hyperx_cloud_battery():
    if hid is None:
        return None

    for pid in (0x05B7, 0x0C9D):
        for info in hid.enumerate(0x03F0, pid):
            if info.get("usage_page") == 0xFF13 or info.get("interface_number") == 3:
                h = None
                try:
                    h = hid.device()
                    h.open_path(info["path"])
                    h.set_nonblocking(1)

                    while h.read(64):
                        pass

                    h.write([102, 130] + [0] * 60)
                    time.sleep(0.045)
                    r_conn = h.read(64)
                    if not r_conn or r_conn[0] != 102:
                        h.close()
                        continue

                    connected = len(r_conn) > 2 and r_conn[2] == 1
                    if not connected:
                        h.close()
                        return {
                            "connected": False,
                            "battery": None,
                            "charging": False,
                            "model": "HyperX Cloud III Wireless",
                        }

                    h.write([102, 137] + [0] * 60)
                    time.sleep(0.045)
                    r_bat = h.read(64)
                    battery = None
                    if r_bat and len(r_bat) > 4 and r_bat[0] == 102 and r_bat[1] in (137, 13):
                        if (r_bat[2] != 0 or r_bat[3] != 0) and 0 <= r_bat[4] <= 100:
                            battery = int(r_bat[4])

                    h.write([102, 138] + [0] * 60)
                    time.sleep(0.045)
                    r_chg = h.read(64)
                    charging = False
                    if r_chg and len(r_chg) > 2 and r_chg[0] == 102 and r_chg[1] in (138, 12):
                        charging = r_chg[2] == 1

                    h.close()
                    return {
                        "connected": True,
                        "battery": battery,
                        "charging": charging,
                        "model": "HyperX Cloud III Wireless",
                    }
                except Exception:
                    if h:
                        try:
                            h.close()
                        except Exception:
                            pass

    return None
