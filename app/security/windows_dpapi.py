from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class SecretProtectionError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapiSecretCipher:
    _DESCRIPTION = "WeInsight authorization settings"

    def __init__(self) -> None:
        if os.name != "nt":
            raise SecretProtectionError("dpapi_unavailable")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob), wintypes.LPVOID, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob), wintypes.LPVOID, wintypes.LPVOID,
            wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    def encrypt(self, value: str) -> bytes:
        if not isinstance(value, str) or not value:
            raise ValueError("secret must be a non-empty string")
        raw = value.encode("utf-8")
        source, source_buffer = _blob(raw)
        output = _DataBlob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), self._DESCRIPTION, None, None, None, 0,
            ctypes.byref(output),
        ):
            raise SecretProtectionError("dpapi_encrypt_failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def decrypt(self, value: bytes) -> str:
        if not isinstance(value, bytes) or not value:
            raise ValueError("encrypted secret must be non-empty bytes")
        source, source_buffer = _blob(value)
        output = _DataBlob()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0,
            ctypes.byref(output),
        ):
            raise SecretProtectionError("dpapi_decrypt_failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
        except UnicodeDecodeError:
            raise SecretProtectionError("dpapi_decrypt_failed") from None
        finally:
            self._kernel32.LocalFree(output.pbData)


def _blob(value: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(value, len(value))
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer
