'''
Copyright 2011 Mikel Azkolain

This file is part of Spotimc.

Spotimc is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Spotimc is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Spotimc.  If not, see <http://www.gnu.org/licenses/>.
'''


import xbmc
import xbmcgui
import time
from spotify import ErrorType, SessionEvent
from __main__ import __addon_path__


class LoginCallbacks(object):
    __dialog = None

    def __init__(self, dialog):
        self.__dialog = dialog

    def logged_in(self, session, err):
        xbmc.log('log in callback called...')
        if err == 0:
            xbmc.log('log in callback successful...')
            self.__dialog.do_close()

        else:
            xbmc.log('log in callback error...')
            self.__dialog.set_error(err)

    def add_callbacks(self, session):
        session.on(SessionEvent.LOGGED_IN, self.logged_in)

    def remove_callbacks(self, session):
        session.off(SessionEvent.LOGGED_IN, self.logged_in)


class LoginWindow(xbmcgui.WindowXMLDialog):
    #Controld id's
    username_input = 1101
    password_input = 1102
    login_button = 1104
    cancel_button = 1105

    login_container = 1000
    fields_container = 1100
    loading_container = 1200

    __file = None
    __script_path = None
    __skin_dir = None
    __session = None
    __callbacks = None
    __app = None

    __username = None
    __password = None

    __cancelled = None

    def __init__(self, file, script_path, skin_dir):
        self.__file = file
        self.__script_path = script_path
        self.__skin_dir = skin_dir
        self.__cancelled = False

    def initialize(self, session, app):
        self.__session = session
        self.__callbacks = LoginCallbacks(self)
        self.__callbacks.add_callbacks(self.__session)
        self.__app = app

    def onInit(self):
        #If there is a remembered user, show it's login name
        username = self.__session.remembered_user_name
        if username is not None:
            self._set_input_value(self.username_input, username)

        #Show useful info if previous errors are present
        if self.__app.has_var('login_last_error'):

            #If the error number was relevant...
            login_last_error = self.__app.get_var('login_last_error')
            if login_last_error != 0:
                #Wait for the appear animation to complete
                time.sleep(0.2)

                self.set_error(self.__app.get_var('login_last_error'), True)

    def onAction(self, action):
        if action.getId() in [9, 10, 92]:
            self.__cancelled = True
            self.do_close()

    def set_error(self, code, short_animation=False):
        messages = {
            ErrorType.CLIENT_TOO_OLD: 'Client is too old',
            ErrorType.UNABLE_TO_CONTACT_SERVER: 'Unable to contact server',
            ErrorType.BAD_USERNAME_OR_PASSWORD: 'Bad username or password',
            ErrorType.USER_BANNED: 'User is banned',
            ErrorType.USER_NEEDS_PREMIUM: 'A premium account is required',
            ErrorType.OTHER_TRANSIENT: 'A transient error occurred.'
            'Try again after a few minutes.',
            ErrorType.OTHER_PERMANENT: 'A permanent error occurred.',
        }

        if code in messages:
            escaped = messages[code].replace('"', '\"')
            tmpStr = 'SetProperty(LoginErrorMessage, "{0}")'.format(escaped)
            xbmc.executebuiltin(tmpStr)
        else:
            tmpStr = 'SetProperty(LoginErrorMessage, "Unknown error.")'
            xbmc.executebuiltin(tmpStr)
            #self.setProperty('LoginErrorMessage', 'Unknown error.')

        #Set error flag
        xbmc.executebuiltin('SetProperty(IsLoginError,true)')

        #Animation type
        if short_animation:
            xbmc.executebuiltin('SetProperty(ShortErrorAnimation,true)')
        else:
            xbmc.executebuiltin('SetProperty(ShortErrorAnimation,false)')

        #Hide animation
        self.getControl(
            LoginWindow.loading_container).setVisibleCondition('false')

    def _get_input_value(self, controlID):
        c = self.getControl(controlID)
        return c.getLabel()

    def _set_input_value(self, controlID, value):
        c = self.getControl(controlID)
        c.setLabel(value)

    def do_login(self):
        xbmc.log('doing login')
        remember_set = xbmc.getCondVisibility(
            'Skin.HasSetting(spotimc_session_remember)'
        )

        xbmc.log('sending login')
        self.__session.login(self.__username, self.__password, remember_set)

        xbmc.log('login sent')
        #Clear error status
        xbmc.executebuiltin('SetProperty(IsLoginError,false)')

        #SHow loading animation
        self.getControl(
            LoginWindow.loading_container).setVisibleCondition('true')

        self.do_close()

    def do_close(self):
        xbmc.log('removing callbacks')
        self.__callbacks.remove_callbacks(self.__session)

        xbmc.log('callbacks removed')
        c = self.getControl(LoginWindow.login_container)
        c.setVisibleCondition("False")
        time.sleep(0.2)

        xbmc.log('closing')
        self.close()
        xbmc.log('closed')

    def onClick(self, controlID):
        if controlID == self.username_input:
            default = self._get_input_value(controlID)
            kb = xbmc.Keyboard(default, "Enter username")
            kb.setHiddenInput(False)
            kb.doModal()
            if kb.isConfirmed():
                value = kb.getText()
                self.__username = value
                self._set_input_value(controlID, value)

        elif controlID == self.password_input:
            kb = xbmc.Keyboard("", "Enter password")
            kb.setHiddenInput(True)
            kb.doModal()
            if kb.isConfirmed():
                value = kb.getText()
                self.__password = value
                self._set_input_value(controlID, "*" * len(value))

        elif controlID == self.login_button:
            self.do_login()

        elif controlID == self.cancel_button:
            self.__cancelled = True
            self.do_close()

    def is_cancelled(self):
        return self.__cancelled

    def onFocus(self, controlID):
        pass


class TextViewer(xbmcgui.WindowXMLDialog):
    label_id = 1
    textbox_id = 5
    close_button_id = 10

    __heading = None
    __text = None

    def onInit(self):
        #Not all skins implement the heading label...
        try:
            self.getControl(TextViewer.label_id).setLabel(self.__heading)
        except:
            pass

        self.getControl(TextViewer.textbox_id).setText(self.__text)

    def onClick(self, control_id):
        if control_id == 10:
            self.close()

    def initialize(self, heading, text):
        self.__heading = heading
        self.__text = text


def text_viewer_dialog(heading, text, modal=True):
    tv = TextViewer('DialogTextViewer.xml', __addon_path__)
    tv.initialize(heading, text)

    if modal:
        tv.doModal()
    else:
        tv.show()
