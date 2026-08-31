from gettext import gettext
import gettext as gettext
import os
from tkinter import StringVar as strVar

gettext.bindtextdomain('steam_uploader', 'locale')
gettext.textdomain('steam_uploader')
_ = gettext.gettext

TEXT_LIST = {
    "header"                :       _("Mush Dash Workshop Uploader")                                       ,
    "headerDesc"            :       _("by Nerux-Network.de, modified by CrazyDog")                         ,
    "appId"                 :       _("App ID (Mush Dash = 3026250)")                                      ,
    "fileId"                :       _("File ID")                                                           ,
    "title"                 :       _("Title *")                                                           ,
    "desc"                  :       _("Description")                                                       ,
    "content"               :       _("Content (Folder only) *")                                           ,
    "chooseFolder"          :       _("Choose folder ...")                                                 ,
    "clear"                 :       _("Clear")                                                             ,
    "previewImg"            :       _("Preview image (PNG/JPG, < 1 MB)")                                   ,
    "choPrevImg"            :       _("Choose preview image ...")                                          ,
    "apiDll"                :       _("Path to steam_api64.dll (optional, otherwise next to the tool)")    ,
    "updateContOnly"        :       _("Update Content Only")                                               ,
    "upload"                :       _("Upload")                                                            ,
    "visibility"            :       _("Visibility")                                                        ,
    "tags"                  :       _("Tags (comma-separated, optional)")                                  ,
    "log"                   :       _("Log")                                                               ,
}

class language_object:
    def __init__(self):
        self.folder_list = os.listdir("locale")
        self.current_language = self.folder_list[0]
        self.translator = gettext.translation("text", localedir="locale", languages=[self.current_language])
        self.TEXT_VAR_LIST = {}
        self.init_text_vars()

    def init_text_vars(self):
        for text in TEXT_LIST.keys():
            self.TEXT_VAR_LIST[text] = strVar(value=self.translator.gettext(TEXT_LIST.get(text)))

    def update_text_value(self):
        for text in TEXT_LIST:
            self.TEXT_VAR_LIST[text].set(self.translator.gettext(TEXT_LIST.get(text)))

    def get_text_value(self, name:str):
        return self.TEXT_VAR_LIST.get(name)

    def get_language_list(self):
        return self.folder_list

    def set_language(self, language):
        current_language = language
        self.translator = gettext.translation("text", localedir="locale", languages=[current_language])
        self.update_text_value()