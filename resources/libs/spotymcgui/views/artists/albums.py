'''
Created on 29/11/2011

@author: mikel
'''
import xbmc, xbmcgui
from spotymcgui.views import BaseListContainerView, album
from loaders import ArtistAlbumLoader



class ArtistAlbumsView(BaseListContainerView):
    container_id = 2000
    list_id = 2001
    
    
    __artist = None
    __loader = None
    
    
    def __init__(self, session, artist):
        self.__artist = artist
        self.__loader = ArtistAlbumLoader(session, artist)
        
    
    #def _show_album(self, view_manager):
    #    pos = self.get_list(view_manager).getSelectedPosition()
    #    v = album.AlbumTracksView(self.__session, self.__search.album(pos))
    #    view_manager.add_view(v)
    
    def _show_album(self, view_manager):
        item = self.get_list(view_manager).getSelectedItem()
        real_index = int(item.getProperty('real_index'))
        album_obj = self.__loader.get_album(real_index)
        session = view_manager.get_var('session')
        v = album.AlbumTracksView(session, album_obj)
        view_manager.add_view(v)
    
    
    def click(self, view_manager, control_id):
        #If the list was clicked...
        if control_id == ArtistAlbumsView.list_id:
            self._show_album(view_manager)
    
    
    def get_container(self, view_manager):
        return view_manager.get_window().getControl(ArtistAlbumsView.container_id)
    
    
    def get_list(self, view_manager):
        return view_manager.get_window().getControl(ArtistAlbumsView.list_id)
    
    
    def render(self, view_manager):
        if self.__loader.is_loaded():
            l = self.get_list(view_manager)
            l.reset()
            
            
            #Set the artist name
            window = view_manager.get_window()
            window.setProperty('artistbrowse_artist_name', self.__artist.name())
            
            
            for index, album in enumerate(self.__loader.get_albums()):
                #Discard unavailable albums
                if self.__loader.is_album_available(index):
                    item = xbmcgui.ListItem(
                        album.name(), str(album.year()),
                        'http://localhost:8080/image/%s.jpg' % album.cover()
                    )
                    item.setProperty('real_index', str(index))
                    l.addItem(item)
            
            return True