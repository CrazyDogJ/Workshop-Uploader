"""
steam_ugc.py
------------
Thin ctypes binding to steam_api64.dll (Steamworks "flat" API) for creating
and uploading Steam Workshop items.

Flow:
  CreateItem -> StartItemUpdate -> SetItem* -> SubmitItemUpdate

Steam responses (call results) are awaited using the officially recommended
"Manual Dispatch" mechanism. This means the ISteamUtils interface is NOT
required (a common source of errors). If Manual Dispatch is unavailable, there
is a fallback via ISteamUtils.
"""

import ctypes
import os
import sys
import time
from ctypes import (
    c_bool, c_char_p, c_int, c_ubyte, c_uint32, c_uint64, c_void_p,
    Structure, POINTER, byref, cast, sizeof,
)
from steam_postCreate import (
    postItemCreated
)

# ---------------------------------------------------------------------------
# Steam types
# ---------------------------------------------------------------------------
AppId_t = c_uint32
SteamAPICall_t = c_uint64
UGCUpdateHandle_t = c_uint64
PublishedFileId_t = c_uint64
HSteamPipe = c_int
HSteamUser = c_int

k_EResultOK = 1
k_EResultFileNotFound = 9
k_EWorkshopFileTypeCommunity = 0
k_EItemPreviewType_Image = 0

VISIBILITY = {
    "public": 0,     # Public
    "friends": 1,    # Friends only
    "private": 2,    # Private
    "unlisted": 3,   # Unlisted (link only)
}

# Callback IDs
_k_iSteamUGCCallbacks = 3400
CREATE_ITEM_CALLBACK = _k_iSteamUGCCallbacks + 3        # 3403
SUBMIT_UPDATE_CALLBACK = _k_iSteamUGCCallbacks + 4      # 3404

_k_iSteamUtilsCallbacks = 700
STEAM_API_CALL_COMPLETED = _k_iSteamUtilsCallbacks + 3  # 703


class CreateItemResult_t(Structure):
    _pack_ = 8
    _fields_ = [
        ("m_eResult", c_int),
        ("m_nPublishedFileId", PublishedFileId_t),
        ("m_bUserNeedsToAcceptWorkshopLegalAgreement", c_bool),
    ]


class SubmitItemUpdateResult_t(Structure):
    _pack_ = 8
    _fields_ = [
        ("m_eResult", c_int),
        ("m_bUserNeedsToAcceptWorkshopLegalAgreement", c_bool),
        ("m_nPublishedFileId", PublishedFileId_t),
    ]


class SteamParamStringArray_t(Structure):
    _fields_ = [
        ("m_ppStrings", POINTER(c_char_p)),
        ("m_nNumStrings", c_int),
    ]


class CallbackMsg_t(Structure):
    _fields_ = [
        ("m_hSteamUser", HSteamUser),
        ("m_iCallback", c_int),
        ("m_pubParam", POINTER(c_ubyte)),
        ("m_cubParam", c_int),
    ]


class SteamAPICallCompleted_t(Structure):
    _pack_ = 8
    _fields_ = [
        ("m_hAsyncCall", SteamAPICall_t),
        ("m_iCallback", c_int),
        ("m_cubParam", c_uint32),
    ]


class SteamError(Exception):
    pass


def _b(value):
    if value is None:
        return None
    return value.encode("utf-8") if isinstance(value, str) else value


class SteamUGC:
    MUSHDASH_APP_ID = 3026250

    def __init__(self, app_id=MUSHDASH_APP_ID, dll_path=None, log=print):
        self.app_id = int(app_id)
        self.log = log
        self._dll_path = dll_path
        self.lib = None
        self.ugc = None
        self.utils = None          # fallback only
        self.pipe = None
        self._use_manual_dispatch = False

    # ------------------------------------------------------------------ #
    # Load DLL
    # ------------------------------------------------------------------ #
    def _load_dll(self):
        candidates = []
        if self._dll_path:
            candidates.append(self._dll_path)
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        candidates.append(os.path.join(base, "steam_api64.dll"))
        candidates.append("steam_api64.dll")

        last_err = None
        for path in candidates:
            try:
                return ctypes.WinDLL(path)
            except OSError as exc:
                last_err = exc
        raise SteamError(
            "Could not load steam_api64.dll. Place the 64-bit file from the "
            "Steamworks SDK (redistributable_bin/win64) next to the program.\n"
            "Details: %s" % last_err
        )

    def _has(self, name):
        try:
            getattr(self.lib, name)
            return True
        except AttributeError:
            return False

    def _get_flat_interface(self, base_name, versions):
        """Try the versioned flat accessor (e.g. SteamAPI_SteamUGC_v021)."""
        symbol_seen = False
        for ver in versions:
            name = "%s_%s" % (base_name, ver)
            if not self._has(name):
                continue
            symbol_seen = True
            fn = getattr(self.lib, name)
            fn.restype = c_void_p
            fn.argtypes = []
            ptr = fn()
            if ptr:
                return ptr, ver
            self.log("  Note: %s() returned NULL." % name)
        if not symbol_seen:
            self.log("  Note: no %s_vXXX symbol found in the DLL." % base_name)
        return None, None

    def _find_user_interface(self, version_strings):
        """Fallback: SteamInternal_FindOrCreateUserInterface(user, 'SteamUtils010')."""
        if not self._has("SteamInternal_FindOrCreateUserInterface"):
            return None, None
        if not self._has("SteamAPI_GetHSteamUser"):
            return None, None
        self.lib.SteamAPI_GetHSteamUser.restype = HSteamUser
        self.lib.SteamAPI_GetHSteamUser.argtypes = []
        huser = self.lib.SteamAPI_GetHSteamUser()

        fn = self.lib.SteamInternal_FindOrCreateUserInterface
        fn.restype = c_void_p
        fn.argtypes = [HSteamUser, c_char_p]
        for vs in version_strings:
            ptr = fn(huser, _b(vs))
            if ptr:
                return ptr, vs
        return None, None

    # ------------------------------------------------------------------ #
    # Init
    # ------------------------------------------------------------------ #
    def init(self):
        try:
            with open("steam_appid.txt", "w", encoding="ascii") as fh:
                fh.write(str(self.app_id))
        except OSError:
            pass
        os.environ["SteamAppId"] = str(self.app_id)
        os.environ["SteamGameId"] = str(self.app_id)

        self.lib = self._load_dll()

        # -- Initialize SteamAPI ---------------------------------------
        if self._has("SteamAPI_InitFlat"):
            self.lib.SteamAPI_InitFlat.restype = c_int
            self.lib.SteamAPI_InitFlat.argtypes = [c_char_p]
            buf = ctypes.create_string_buffer(1024)
            res = self.lib.SteamAPI_InitFlat(buf)
            if res != 0:
                raise SteamError(
                    "SteamAPI_InitFlat failed (code %d): %s\n"
                    "Is Steam running? Are you logged in and do you own the app "
                    "(App ID %d)?"
                    % (res, buf.value.decode("utf-8", "replace"), self.app_id)
                )
        elif self._has("SteamAPI_Init"):
            self.lib.SteamAPI_Init.restype = c_bool
            self.lib.SteamAPI_Init.argtypes = []
            if not self.lib.SteamAPI_Init():
                raise SteamError(
                    "SteamAPI_Init failed. Is Steam running in the background and "
                    "does your account own the app (App ID %d)?" % self.app_id
                )
        else:
            raise SteamError("No init function found in steam_api64.dll.")

        self.lib.SteamAPI_Shutdown.restype = None
        self.lib.SteamAPI_Shutdown.argtypes = []

        # -- Get ISteamUGC (flat, with a broad version list) -----------
        self.ugc, ugc_ver = self._get_flat_interface(
            "SteamAPI_SteamUGC",
            ["v021", "v020", "v019", "v018", "v017", "v016", "v015", "v014"],
        )
        if not self.ugc:
            raise SteamError(
                "ISteamUGC interface not found. Is your steam_api64.dll up to "
                "date (from a newer Steamworks SDK)?"
            )

        # -- Choose the wait mechanism: Manual Dispatch preferred ------
        md_symbols = (
            "SteamAPI_ManualDispatch_Init",
            "SteamAPI_ManualDispatch_RunFrame",
            "SteamAPI_ManualDispatch_GetNextCallback",
            "SteamAPI_ManualDispatch_FreeLastCallback",
            "SteamAPI_ManualDispatch_GetAPICallResult",
            "SteamAPI_GetHSteamPipe",
        )
        if all(self._has(s) for s in md_symbols):
            self._setup_manual_dispatch()
            self._use_manual_dispatch = True
            self.log("Steam initialized (UGC %s, Manual Dispatch)." % ugc_ver)
        else:
            # Fallback: ISteamUtils (flat accessor, then FindOrCreate)
            self.utils, uver = self._get_flat_interface(
                "SteamAPI_SteamUtils",
                ["v010", "v011", "v009", "v008", "v007", "v006"],
            )
            if not self.utils:
                self.utils, uver = self._find_user_interface(
                    ["SteamUtils010", "SteamUtils011", "SteamUtils009", "SteamUtils008"]
                )
            if not self.utils:
                raise SteamError(
                    "Neither Manual Dispatch nor ISteamUtils is available. Your "
                    "steam_api64.dll seems very old or corrupted - please use a "
                    "current version from the Steamworks SDK."
                )
            self._setup_utils_fallback()
            self.log("Steam initialized (UGC %s, Utils %s)." % (ugc_ver, uver))

        self._bind_ugc_functions()
        return True

    def _setup_manual_dispatch(self):
        lib = self.lib
        lib.SteamAPI_GetHSteamPipe.restype = HSteamPipe
        lib.SteamAPI_GetHSteamPipe.argtypes = []
        lib.SteamAPI_ManualDispatch_Init.restype = None
        lib.SteamAPI_ManualDispatch_Init.argtypes = []
        lib.SteamAPI_ManualDispatch_RunFrame.restype = None
        lib.SteamAPI_ManualDispatch_RunFrame.argtypes = [HSteamPipe]
        lib.SteamAPI_ManualDispatch_GetNextCallback.restype = c_bool
        lib.SteamAPI_ManualDispatch_GetNextCallback.argtypes = [
            HSteamPipe, POINTER(CallbackMsg_t)
        ]
        lib.SteamAPI_ManualDispatch_FreeLastCallback.restype = None
        lib.SteamAPI_ManualDispatch_FreeLastCallback.argtypes = [HSteamPipe]
        lib.SteamAPI_ManualDispatch_GetAPICallResult.restype = c_bool
        lib.SteamAPI_ManualDispatch_GetAPICallResult.argtypes = [
            HSteamPipe, SteamAPICall_t, c_void_p, c_int, c_int, POINTER(c_bool)
        ]
        lib.SteamAPI_ManualDispatch_Init()
        self.pipe = lib.SteamAPI_GetHSteamPipe()

    def _setup_utils_fallback(self):
        lib = self.lib
        if self._has("SteamAPI_RunCallbacks"):
            lib.SteamAPI_RunCallbacks.restype = None
            lib.SteamAPI_RunCallbacks.argtypes = []
        lib.SteamAPI_ISteamUtils_IsAPICallCompleted.restype = c_bool
        lib.SteamAPI_ISteamUtils_IsAPICallCompleted.argtypes = [
            c_void_p, SteamAPICall_t, POINTER(c_bool)
        ]
        lib.SteamAPI_ISteamUtils_GetAPICallResult.restype = c_bool
        lib.SteamAPI_ISteamUtils_GetAPICallResult.argtypes = [
            c_void_p, SteamAPICall_t, c_void_p, c_int, c_int, POINTER(c_bool)
        ]

    def _bind_ugc_functions(self):
        lib = self.lib
        lib.SteamAPI_ISteamUGC_CreateItem.restype = SteamAPICall_t
        lib.SteamAPI_ISteamUGC_CreateItem.argtypes = [c_void_p, AppId_t, c_int]

        lib.SteamAPI_ISteamUGC_StartItemUpdate.restype = UGCUpdateHandle_t
        lib.SteamAPI_ISteamUGC_StartItemUpdate.argtypes = [
            c_void_p, AppId_t, PublishedFileId_t
        ]

        for name in ("SetItemTitle", "SetItemDescription",
                     "SetItemPreview", "SetItemContent"):
            fn = getattr(lib, "SteamAPI_ISteamUGC_%s" % name)
            fn.restype = c_bool
            fn.argtypes = [c_void_p, UGCUpdateHandle_t, c_char_p]

        lib.SteamAPI_ISteamUGC_SetItemVisibility.restype = c_bool
        lib.SteamAPI_ISteamUGC_SetItemVisibility.argtypes = [
            c_void_p, UGCUpdateHandle_t, c_int
        ]

        lib.SteamAPI_ISteamUGC_AddItemPreviewFile.restype = c_bool
        lib.SteamAPI_ISteamUGC_AddItemPreviewFile.argtypes = [
            c_void_p, UGCUpdateHandle_t, c_char_p, c_int
        ]

        lib.SteamAPI_ISteamUGC_SetItemTags.restype = c_bool
        lib.SteamAPI_ISteamUGC_SetItemTags.argtypes = [
            c_void_p, UGCUpdateHandle_t, POINTER(SteamParamStringArray_t)
        ]

        lib.SteamAPI_ISteamUGC_SubmitItemUpdate.restype = SteamAPICall_t
        lib.SteamAPI_ISteamUGC_SubmitItemUpdate.argtypes = [
            c_void_p, UGCUpdateHandle_t, c_char_p
        ]

        lib.SteamAPI_ISteamUGC_GetItemUpdateProgress.restype = c_int
        lib.SteamAPI_ISteamUGC_GetItemUpdateProgress.argtypes = [
            c_void_p, UGCUpdateHandle_t, POINTER(c_uint64), POINTER(c_uint64)
        ]

    # ------------------------------------------------------------------ #
    # Wait for a call result (with optional progress)
    # ------------------------------------------------------------------ #
    def _wait_for_result(self, api_call, result_type, expected_cb,
                         timeout=900, progress_handle=None, progress_cb=None):
        start = time.time()
        processed = c_uint64(0)
        total = c_uint64(0)

        def report_progress():
            if progress_handle is not None and progress_cb:
                self.lib.SteamAPI_ISteamUGC_GetItemUpdateProgress(
                    self.ugc, progress_handle, byref(processed), byref(total)
                )
                if total.value > 0:
                    progress_cb(processed.value, total.value)

        if self._use_manual_dispatch:
            pipe = self.pipe
            while True:
                self.lib.SteamAPI_ManualDispatch_RunFrame(pipe)
                msg = CallbackMsg_t()
                while self.lib.SteamAPI_ManualDispatch_GetNextCallback(pipe, byref(msg)):
                    got = None
                    try:
                        if msg.m_iCallback == STEAM_API_CALL_COMPLETED:
                            comp = cast(
                                msg.m_pubParam,
                                POINTER(SteamAPICallCompleted_t),
                            ).contents
                            if comp.m_hAsyncCall == api_call:
                                res = result_type()
                                failed = c_bool(False)
                                ok = self.lib.SteamAPI_ManualDispatch_GetAPICallResult(
                                    pipe, api_call, byref(res), sizeof(res),
                                    expected_cb, byref(failed),
                                )
                                got = (res, ok and not failed.value)
                    finally:
                        self.lib.SteamAPI_ManualDispatch_FreeLastCallback(pipe)
                    if got is not None:
                        res, ok = got
                        if not ok:
                            raise SteamError("Steam call failed (I/O).")
                        return res
                report_progress()
                if time.time() - start > timeout:
                    raise SteamError("Timeout while waiting for Steam.")
                time.sleep(0.05)
        else:
            failed = c_bool(False)
            while not self.lib.SteamAPI_ISteamUtils_IsAPICallCompleted(
                self.utils, api_call, byref(failed)
            ):
                if self._has("SteamAPI_RunCallbacks"):
                    self.lib.SteamAPI_RunCallbacks()
                report_progress()
                if time.time() - start > timeout:
                    raise SteamError("Timeout while waiting for Steam.")
                time.sleep(0.05)
            res = result_type()
            ok = self.lib.SteamAPI_ISteamUtils_GetAPICallResult(
                self.utils, api_call, byref(res), sizeof(res),
                expected_cb, byref(failed),
            )
            if not ok or failed.value:
                raise SteamError("Steam call failed (I/O).")
            return res

    def _set_tags(self, handle, tags):
        arr = (c_char_p * len(tags))(*[_b(t) for t in tags])
        sps = SteamParamStringArray_t()
        sps.m_ppStrings = cast(arr, POINTER(c_char_p))
        sps.m_nNumStrings = len(tags)
        if not self.lib.SteamAPI_ISteamUGC_SetItemTags(self.ugc, handle, byref(sps)):
            self.log("WARN: Tags could not be set.")

    @staticmethod
    def _eresult_hint(code):
        return {
            2:  "Generic error.",
            8:  "File not found / preview image missing or too small.",
            10: "Steam is busy - wait a moment and try again.",
            15: "Access denied - app not owned, or ISteamUGC not enabled in the "
                "App Admin panel.",
            16: "Timeout.",
            25: "Limit exceeded (e.g. preview image larger than 1 MB).",
        }.get(code, "")

    # ------------------------------------------------------------------ #
    # Upload
    # ------------------------------------------------------------------ #
    def createItem(self):
        self.log("Creating new Workshop item ...")
        call = self.lib.SteamAPI_ISteamUGC_CreateItem(
            self.ugc, self.app_id, k_EWorkshopFileTypeCommunity
        )
        res = self._wait_for_result(call, CreateItemResult_t, CREATE_ITEM_CALLBACK)
        if res.m_eResult != k_EResultOK:
            raise SteamError("CreateItem failed (EResult=%d). %s"
                             % (res.m_eResult, self._eresult_hint(res.m_eResult)))
    
        published_id = res.m_nPublishedFileId
        self.log("Item created. PublishedFileId = %d" % published_id)
        if res.m_bUserNeedsToAcceptWorkshopLegalAgreement:
            self.log("NOTE: Workshop legal agreement not accepted yet. Open the "
                     "item page in your browser and accept it.")
            
        return published_id

    def upload(self, only_content, file_id, title, description, content_folder, preview_file=None,
               visibility="public", tags=None, change_note="Initial upload",
               progress_cb=None, extra_previews=None):
        content_folder = os.path.abspath(content_folder)
        if preview_file:
            preview_file = os.path.abspath(preview_file)

        # 1) TryExistItem
        if (file_id != 0):
            self.log("Try uploading using file id : %d ..." % published_id)
            published_id = file_id
        else:
            published_id = self.createItem()

        # 2) PostItemIdCreate
        self.log("Post Workshop item created, using id : %d" % published_id)
        postItemCreated(content_folder, published_id)

        # 3) StartItemUpdate
        handle = self.lib.SteamAPI_ISteamUGC_StartItemUpdate(
            self.ugc, self.app_id, published_id
        )

        # 4) Set fields
        if not self.lib.SteamAPI_ISteamUGC_SetItemContent(
                    self.ugc, handle, _b(content_folder)
                ):
                    self.log("WARN: Content folder could not be set.")
        if not only_content:
            if not self.lib.SteamAPI_ISteamUGC_SetItemTitle(self.ugc, handle, _b(title)):
                self.log("WARN: Title could not be set.")
            if not self.lib.SteamAPI_ISteamUGC_SetItemDescription(
                self.ugc, handle, _b(description)
            ):
                self.log("WARN: Description could not be set.")
            if preview_file:
                if not self.lib.SteamAPI_ISteamUGC_SetItemPreview(
                    self.ugc, handle, _b(preview_file)
                ):
                    self.log("WARN: Preview image could not be set.")

        # Additional preview images -> show up in the item's gallery
        added = 0
        for extra in (extra_previews or []):
            path = os.path.abspath(extra)
            if self.lib.SteamAPI_ISteamUGC_AddItemPreviewFile(
                self.ugc, handle, _b(path), k_EItemPreviewType_Image
            ):
                added += 1
            else:
                self.log("WARN: Could not add preview image '%s'."
                         % os.path.basename(path))
        if added:
            self.log("Added %d image(s) to the preview gallery." % added)
        self.lib.SteamAPI_ISteamUGC_SetItemVisibility(
            self.ugc, handle, VISIBILITY.get(visibility, 0)
        )
        if tags:
            self._set_tags(handle, tags)

        # 5) SubmitItemUpdate + progress
        self.log("Uploading ...")
        submit_call = self.lib.SteamAPI_ISteamUGC_SubmitItemUpdate(
            self.ugc, handle, _b(change_note)
        )
        submit_res = self._wait_for_result(
            submit_call, SubmitItemUpdateResult_t, SUBMIT_UPDATE_CALLBACK,
            progress_handle=handle, progress_cb=progress_cb,
        )
        if submit_res.m_eResult == k_EResultFileNotFound:
            if not only_content:
                # Create item and retry.
                self.log("File id : %d is not valid, trying to create a new one." % published_id)
                published_id = self.createItem()
                self.upload(
                    file_id=file_id,
                    title=title,
                    description=description,
                    content_folder=content_folder,
                    preview_file=preview_file,
                    extra_previews=extra_previews,
                    visibility=visibility,
                    tags=tags,
                    progress_cb=progress_cb,
                )

        if submit_res.m_eResult != k_EResultOK:
            raise SteamError("Upload failed (EResult=%d). %s"
                             % (submit_res.m_eResult,
                                self._eresult_hint(submit_res.m_eResult)))

        if progress_cb:
            progress_cb(1, 1)
        url = "https://steamcommunity.com/sharedfiles/filedetails/?id=%d" % published_id
        self.log("Done! Item URL: %s" % url)
        return published_id, url

    def shutdown(self):
        if self.lib:
            try:
                self.lib.SteamAPI_Shutdown()
            except Exception:
                pass
