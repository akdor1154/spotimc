'''
Created on 24/06/2011

@author: mikel
'''
import xbmcgui
import views
#import views.home
import views.newstuff
import views.album
import views.artist
import views.search
import views.nowplaying
import views.playlist

import dialogs


class MainWindow(xbmcgui.WindowXML): 
    __file = None
    __script_path = None
    __skin_dir = None
    __view_manager = None
    __session = None
    
    
    def __init__(self, file, script_path, skin_dir, session):
        self.__file = file
        self.__script_path = script_path
        self.__skin_dir = skin_dir
        self.__view_manager = views.ViewManager(self)
        self.__session = session


    def _login(self):
        loginwin = dialogs.LoginWindow(
            "login-window.xml", self.__script_path, self.__skin_dir, self.__session
        )
        loginwin.doModal()
        del loginwin


    def onInit(self):
        self._login()
        
        #Start the new stuff view
        v = views.newstuff.NewStuffView(self.__session)
        #v = views.album.AlbumTracksView()
        #v = views.artist.ArtistTracksView()
        #v = views.search.SearchTracksView()
        #v = views.nowplaying.NowPlayingView()
        #v = views.playlist.PlaylistView()
        self.__view_manager.add_view(v)
        
    
    #def onAction(self, action):
    #    print "mainwin: on action called"
    
    
    def onClick(self, control_id):
        self.__view_manager.click(control_id)
        
    
    def onFocus(self, controlID):
        pass
