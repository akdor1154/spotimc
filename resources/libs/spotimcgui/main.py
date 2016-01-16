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


import os
import os.path
import xbmc
import xbmcgui
import windows
import threading
import gc
import traceback
import weakref
import dialogs
import playback
import re
from appkey import appkey
import spotify
from spotify import EventLoop, ConnectionState, ErrorType, Bitrate
from spotify import Track, TrackAvailability
from spotify.session import Session, SessionEvent
from spotifyproxy.httpproxy import ProxyRunner
from spotifyproxy.audio import BufferManager
from taskutils.decorators import run_in_thread
from taskutils.threads import TaskManager
from threading import Event
from settings import SettingsManager, CacheManagement, StreamQuality, \
    GuiSettingsReader, InfoValueManager
from __main__ import __addon_version__, __addon_path__
from utils.logs import get_logger, setup_logging
from utils.gui import hide_busy_dialog, show_busy_dialog

import pydevd

class Application:
    __vars = None

    def __init__(self):
        self.__vars = {}

    def set_var(self, name, value):
        self.__vars[name] = value

    def has_var(self, name):
        return name in self.__vars

    def get_var(self, name):
        return self.__vars[name]

    def remove_var(self, name):
        del self.__vars[name]


class SpotimcCallbacks(object):
    __audio_buffer = None
    __logout_event = None
    __app = None
    __logger = None
    __log_regex = None

    def __init__(self, audio_buffer, app):
        self.__audio_buffer = audio_buffer
        self.__app = app
        self.__logger = get_logger()
        self.__log_regex = re.compile('[0-9]{2}:[0-9]{2}:[0-9]{2}'
                                      '\.[0-9]{3}\s(W|I|E)\s')

    def logged_in(self, session, error_num):
        #Log this event
        self.__logger.debug('logged in: {0:d}'.format(error_num))

        #Store last error code
        self.__app.set_var('login_last_error', error_num)

        #Take action if error status is not ok
        if error_num != ErrorType.OK:

            #Close the main window if it's running
            if self.__app.has_var('main_window'):
                self.__app.get_var('main_window').close()

            #Otherwise, set the connstate event
            else:
                self.__app.get_var('connstate_event').set()

    def logged_out(self, session):
        self.__logger.debug('logged out')
        self.__app.get_var('logout_event').set()

    def connection_error(self, session, error):
        self.__logger.error('connection error: {0:d}'.format(error))

    def message_to_user(self, session, data):
        self.__logger.info('message to user: {0}'.format(data))

    def _get_log_message_level(self, message):
        matches = self.__log_regex.match(message)
        if matches:
            return matches.group(1)

    def log_message(self, session, data):
        message_level = self._get_log_message_level(data)
        if message_level == 'I':
            self.__logger.info(data)
        elif message_level == 'W':
            self.__logger.warning(data)
        else:
            self.__logger.error(data)

    def streaming_error(self, session, error):
        self.__logger.info('streaming error: {0:d}'.format(error))

    @run_in_thread
    def play_token_lost(self, session):

        #Cancel the current buffer
        self.__audio_buffer.stop()

        if self.__app.has_var('playlist_manager'):
            self.__app.get_var('playlist_manager').stop(False)

        dlg = xbmcgui.Dialog()
        dlg.ok('Playback stopped', 'This account is in use on another device.')

    def end_of_track(self, session):
        self.__audio_buffer.set_track_ended()

    def notify_main_thread(self, session):
        session.process_events()

    def music_delivery(self, session, data, num_samples, sample_type,
                       sample_rate, num_channels):
        return self.__audio_buffer.music_delivery(
            data, num_samples, sample_type, sample_rate, num_channels)

    def connectionstate_changed(self, session):

        #Set the apropiate event flag, if available
        self.__app.get_var('connstate_event').set()

    def add_callbacks(self, session):
        session.on(SessionEvent.LOGGED_IN, self.logged_in)
        session.on(SessionEvent.LOGGED_OUT, self.logged_out)
        session.on(SessionEvent.CONNECTION_ERROR, self.connection_error)
        session.on(SessionEvent.MESSAGE_TO_USER, self.message_to_user)
        session.on(SessionEvent.LOG_MESSAGE, self.log_message)
        session.on(SessionEvent.STREAMING_ERROR, self.streaming_error)
        session.on(SessionEvent.PLAY_TOKEN_LOST, self.play_token_lost)
        session.on(SessionEvent.END_OF_TRACK, self.end_of_track)
        session.on(SessionEvent.NOTIFY_MAIN_THREAD, self.notify_main_thread)
        session.on(SessionEvent.MUSIC_DELIVERY, self.music_delivery)
        session.on(SessionEvent.CONNECTION_STATE_UPDATED, self.connectionstate_changed)


class MainLoopRunner(threading.Thread):
    __mainloop = None
    __session = None
    __proxy = None

    def __init__(self, mainloop, session):
        threading.Thread.__init__(self)
        self.__mainloop = mainloop
        self.__session = weakref.proxy(session)

    def run(self):
        self.__mainloop.start()

    def stop(self):
        self.__mainloop.stop()
        self.join(10)


def show_legal_warning(settings_obj):
    shown = settings_obj.get_legal_warning_shown()
    if not shown:
        settings_obj.set_legal_warning_shown(True)
        d = xbmcgui.Dialog()
        l1 = 'Spotimc uses SPOTIFY(R) CORE but is not endorsed,'
        l2 = 'certified or otherwise approved in any way by Spotify.'
        
        hide_busy_dialog()
        d.ok('Spotimc', l1, l2)
        show_busy_dialog()


def check_addon_version(settings_obj):
    last_run_version = settings_obj.get_last_run_version()

    #If current version is higher than the stored one...
    if __addon_version__ > last_run_version:
        settings_obj.set_last_run_version(__addon_version__)

        #Don't display the upgrade message if it's the first run
        if last_run_version != '':
            
            d = xbmcgui.Dialog()
            l1 = 'Spotimc was updated since the last run.'
            l2 = 'Do you want to see the changelog?'
            
            hide_busy_dialog()
            
            if d.yesno('Spotimc', l1, l2):
                file = settings_obj.get_addon_obj().getAddonInfo('changelog')
                changelog = open(file).read()
                dialogs.text_viewer_dialog('ChangeLog', changelog)
            
            show_busy_dialog()
            


def get_audio_buffer_size():
    #Base buffer setting will be 10s
    buffer_size = 10

    try:
        reader = GuiSettingsReader()
        value = reader.get_setting('settings.musicplayer.crossfade')
        buffer_size += int(value)

    except:
        xbmc.log(
            'Failed reading crossfade setting. Using default value.',
            xbmc.LOGERROR
        )

    return buffer_size


def check_dirs():
    addon_data_dir = os.path.join(
        xbmc.translatePath('special://profile/addon_data'),
        'script.audio.spotimc'
    )

    #Auto-create profile dir if it does not exist
    if not os.path.exists(addon_data_dir):
        os.makedirs(addon_data_dir)

    #Libspotify cache & settings
    sp_cache_dir = os.path.join(addon_data_dir, 'libspotify/cache')
    sp_settings_dir = os.path.join(addon_data_dir, 'libspotify/settings')

    if not os.path.exists(sp_cache_dir):
        os.makedirs(sp_cache_dir)

    if not os.path.exists(sp_settings_dir):
        os.makedirs(sp_settings_dir)

    return (addon_data_dir, sp_cache_dir, sp_settings_dir)


def set_settings(settings_obj, session):
    #If cache is enabled set the following one
    if settings_obj.get_cache_status():
        if settings_obj.get_cache_management() == CacheManagement.Manual:
            cache_size_mb = settings_obj.get_cache_size() * 1024
            session.set_cache_size(cache_size_mb)

    #Bitrate config
    br_map = {
        StreamQuality.Low: Bitrate.BITRATE_96k,
        StreamQuality.Medium: Bitrate.BITRATE_160k,
        StreamQuality.High: Bitrate.BITRATE_320k,
    }
    session.preferred_bitrate(br_map[settings_obj.get_audio_quality()])

    #And volume normalization
    session.volume_normalization = settings_obj.get_audio_normalize()



def do_login(session, script_path, skin_dir, app):
    #Get the last error if we have one
    xbmc.log('doing login')
    if app.has_var('login_last_error'):
        prev_error = app.get_var('login_last_error')
    else:
        prev_error = 0

    xbmc.log('checked errors')

    #If no previous errors and we have a remembered user
    if prev_error == 0 and session.remembered_user_name is not None:
        session.relogin()
        status = True
        xbmc.log('existing user check done')

    #Otherwise let's do a normal login process
    else:
        xbmc.log('doing loginwindow')
        loginwin = dialogs.LoginWindow(
            "login-window.xml", script_path, skin_dir
        )
        loginwin.initialize(session, app)
        xbmc.log('going modal')
        try:
            loginwin.doModal()
        except Exception as e:
            xbmc.log('error!')
            xbmc.log(e)
        xbmc.log('modal done')
        status = not loginwin.is_cancelled()

    xbmc.log('returning')
    return status


def login_get_last_error(app):
    if app.has_var('login_last_error'):
        return app.get_var('login_last_error')
    else:
        return 0


def wait_for_connstate(session, app, state):
    xbmc.log('waiting')
    #Store the previous login error number
    last_login_error = login_get_last_error(app)

    xbmc.log('got error')
    #Add a shortcut to the connstate event
    cs = app.get_var('connstate_event')

    xbmc.log('got cs')
    #Wrap all the tests for the following loop
    def continue_loop():

        xbmc.log('looping from start..')
        #Get the current login error
        cur_login_error = login_get_last_error(app)

        #Continue the loop while these conditions are met:
        #  * An exit was not requested
        #  * Connection state was not the desired one
        #  * No login errors where detected
        return (
            not app.get_var('exit_requested') and
            session.connection.state != state and (
                last_login_error == cur_login_error or
                cur_login_error == ErrorType.OK
            )
        )

    #Keep testing until conditions are met
    while continue_loop():
        xbmc.log('waiting..')
        cs.wait(5)
        cs.clear()

    return session.connection.state == state


def get_preloader_callback(session, playlist_manager, buffer):
    session = weakref.proxy(session)

    def preloader():
        next_track = playlist_manager.get_next_item(session)
        if next_track is not None:
            ta = next_track.availability
            if ta == TrackAvailability.Available:
                buffer.open(session, next_track)

    return preloader


def gui_main(addon_dir):
    #Initialize app var storage

    pydevd.settrace('localhost', port=5555, stdoutToServer=True, stderrToServer=True)

    xbmc.log('gui_main reached!')
    app = Application()
    xbmc.log('application reached!')
    logout_event = Event()
    xbmc.log('logout reached!')
    connstate_event = Event()
    xbmc.log('constate reached!')
    info_value_manager = InfoValueManager()
    xbmc.log('valman reached!')
    app.set_var('logout_event', logout_event)
    app.set_var('login_last_error', ErrorType.OK)
    app.set_var('connstate_event', connstate_event)
    app.set_var('exit_requested', False)
    app.set_var('info_value_manager', info_value_manager)

    xbmc.log('vars set!')
    #Check needed directories first
    data_dir, cache_dir, settings_dir = check_dirs()

    xbmc.log('dirs checked!')
    #Instantiate the settings obj
    settings_obj = SettingsManager()

    xbmc.log('settings made!')
    #Show legal warning
    show_legal_warning(settings_obj)

    xbmc.log('legal reached!')
    #Start checking the version
    check_addon_version(settings_obj)

    xbmc.log('version reached!')
    #Don't set cache folder if it's disabled
    if not settings_obj.get_cache_status():
        cache_dir = ''


    xbmc.log('spotify reached!')

    #Initialize spotify stuff
    buf = BufferManager(get_audio_buffer_size())
    xbmc.log('buffermanager created!')
    callbacks = SpotimcCallbacks(buf, app)

    xbmc.log('spotimc callbacks made!')
    session_config = spotify.Config()
    xbmc.log('appkey reached')
    session_config.application_key = bytes(bytearray(appkey))
    xbmc.log('appkey set')
    session_config.user_agent = "python ctypes bindings"
    xbmc.log('agent set')
    session_config.cache_location = cache_dir
    xbmc.log('cache reached')
    session_config.settings_location = settings_dir
    xbmc.log('settings reached')
    session_config.initially_unload_playlists = False

    xbmc.log('about to make session')
    sess = Session(session_config)

    xbmc.log('session created!')
    callbacks.add_callbacks(sess)

    xbmc.log('callbacks registered!')


    ml = EventLoop(sess)
    xbmc.log('eventloop created!')

    #Now that we have a session, set settings
    set_settings(settings_obj, sess)
    xbmc.log('settings set!')
    #Initialize libspotify's main loop handler on a separate thread
    ml_runner = MainLoopRunner(ml, sess)
    xbmc.log('mainlooprunner created!')
    ml_runner.start()
    xbmc.log('mainlooprunner started!')

    #Stay on the application until told to do so
    while not app.get_var('exit_requested'):

        #Set the exit flag if login was cancelled
        if not do_login(sess, addon_dir, "DefaultSkin", app):
            app.set_var('exit_requested', True)

            xbmc.log('login failed!!')

        #Otherwise block until state is sane, and continue
        elif wait_for_connstate(sess, app, ConnectionState.LOGGED_IN):
            xbmc.log('connected!')
            proxy_runner = ProxyRunner(sess, buf, host='127.0.0.1',
                                       allow_ranges=True)
            proxy_runner.start()
            log_str = 'starting proxy at port {0}'.format(
                proxy_runner.get_port())
            get_logger().info(log_str)

            #Instantiate the playlist manager
            playlist_manager = playback.PlaylistManager(proxy_runner)
            app.set_var('playlist_manager', playlist_manager)

            #Set the track preloader callback
            preloader_cb = get_preloader_callback(sess, playlist_manager, buf)
            proxy_runner.set_stream_end_callback(preloader_cb)

            hide_busy_dialog()
            mainwin = windows.MainWindow("main-window.xml",
                                         addon_dir,
                                         "DefaultSkin")
            mainwin.initialize(sess, proxy_runner, playlist_manager, app)
            app.set_var('main_window', mainwin)
            mainwin.doModal()
            show_busy_dialog()

            #Playback and proxy deinit sequence
            proxy_runner.clear_stream_end_callback()
            playlist_manager.stop()
            proxy_runner.stop()
            buf.cleanup()

            #Join all the running tasks
            tm = TaskManager()
            tm.cancel_all()

            #Clear some vars and collect garbage
            proxy_runner = None
            preloader_cb = None
            playlist_manager = None
            mainwin = None
            app.remove_var('main_window')
            app.remove_var('playlist_manager')
            gc.collect()

            #Logout
            if sess.user is not None:
                sess.logout()
                logout_event.wait(10)

    #Stop main loop
    ml_runner.stop()

    #Some deinitializations
    info_value_manager.deinit()


def main():

    setup_logging()

    #Look busy while everything gets initialized
    show_busy_dialog()

    #Surround the rest of the init process
    try:

        #Set font & include manager vars
        fm = None
        im = None

        #And perform the rest of the import statements
        from utils.environment import set_dll_paths
        from skinutils import reload_skin
        from skinutils.fonts import FontManager
        from skinutils.includes import IncludeManager

        #Add the system specific library path
        set_dll_paths('resources/dlls')

        #Install custom fonts
        fm = FontManager()
        skin_dir = os.path.join(__addon_path__, "resources/skins/DefaultSkin")
        xml_path = os.path.join(skin_dir, "720p/font.xml")
        font_dir = os.path.join(skin_dir, "fonts")
        fm.install_file(xml_path, font_dir)

        #Install custom includes
        im = IncludeManager()
        include_path = os.path.join(skin_dir, "720p/includes.xml")
        im.install_file(include_path)
        reload_skin()

        #Show the busy dialog again after reload_skin(), as it may go away
        show_busy_dialog()

        #Load & start the actual gui, no init code beyond this point
        gui_main(__addon_path__)

        show_busy_dialog()

        #Do a final garbage collection after main
        gc.collect()

        #from _spotify.utils.moduletracker import _tracked_modules
        #print "tracked modules after: %d" % len(_tracked_modules)

        #import objgraph
        #objgraph.show_backrefs(_tracked_modules, max_depth=5)

    except (SystemExit, Exception) as ex:
        if str(ex) != '':
            dlg = xbmcgui.Dialog()
            dlg.ok(ex.__class__.__name__, str(ex))
            traceback.print_exc()

    finally:

        #Cleanup includes and fonts
        if im is not None:
            del im

        if fm is not None:
            del fm

        #Close the background loading window
        #loadingwin.close()
        hide_busy_dialog()
