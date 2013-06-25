'''
v.0.0.1

LDSReplicate -  ldsrepl

Copyright 2011 Crown copyright (c)
Land Information New Zealand and the New Zealand Government.
All rights reserved

This program is released under the terms of the new BSD license. See the 
LICENSE file for more information.

Created on 13/02/2013

@author: jramsay
'''

from PyQt4.QtGui import (QApplication, QLabel, QComboBox,
                         QVBoxLayout, QHBoxLayout, QGridLayout,QAbstractItemView,
                         QSizePolicy,QSortFilterProxyModel, QTextBrowser,
                         QMainWindow, QFrame, QStandardItemModel, 
                         QLineEdit,QToolTip, QFont, QHeaderView, 
                         QPushButton, QTableView,QMessageBox, QGroupBox)
from PyQt4.QtCore import (Qt, QCoreApplication, QAbstractTableModel, QVariant, QRect,SIGNAL)



import re
import json

from lds.TransferProcessor import TransferProcessor, LORG
from lds.DataStore import DataStore
from lds.LDSUtilities import LDSUtilities, ConfigInitialiser
from lds.VersionUtilities import AppVersion

ldslog = LDSUtilities.setupLogging()

__version__ = AppVersion.getVersion()

HCOLS = 2

#Notes:
#MS and PG settings entered in these dialogs are saved to config only
#When a new FGDB directory is set in the file dialog using the NewFolder button a new directory is created and a reference added to the user config
#When a new SLITE file is created by entering its name in the SL file dialog, it isnt created but a reference to it is put in the user config file
       
class ConfigConnector(object):

    def __init__(self,uconf,lgval,destname,internal):
        #HACK. Since we cant init an lg list without first intialising read connections must assume lgval is stored in v:x format. 
        #NOTE. This a controlled call to TP and we cant assume TP will be called with a v:x layer/group (since names are allowed)
        #NOTE. Every time a new CC is created we call LDs for a caps doc even though this is mostly invariant
        self.vlayers = None        
        self.initConnections(uconf,lgval,destname,internal)
        
    def initConnections(self,uconf,lgval,destname,internal):
        #write a refresh CC instead of re initialising the whole object, for use when the dest menu changes
        lgpair = (LORG.LAYER if re.match('^v:x',lgval) else LORG.GROUP,lgval) if lgval else (None,None)
        self.tp = TransferProcessor(lgpair, None, None, None, None, None, None, uconf, internal)
        self.lgval = lgval
        self.uconf = uconf
        self.destname = destname
        self.internal = internal
        self.src,self.dst = self.initSrcDst()
        if not self.vlayers:
            self.vlayers = self.getValidLayers(self.dst is not None)
            self.setupReserved()
        self.setupComplete()
        self.setupAssigned()
        self.buildLGList()
        self.inclayers = ['v:x'+x[0] for x in ConfigInitialiser.readCSV()]
    
        
    def initSrcDst(self):
        '''Initialises src and dst objects'''
        #initialise layer data using existing source otherwise use the capabilities doc
        #get SRC here since we need it later for the reserved words anyway
        src = self.tp.src
        #if doing a first run there is no destname
        if self.destname:
            dst = self.tp.initDestination(self.destname)
            #if internal lconf need to init the DB
            if self.tp.getConfInternal()==DataStore.CONF_INT:
                dst.transferIETernal(self.tp.getConfInternal())
                dst.ds = dst.initDS(dst.destinationURI(None))
            dst.setLayerConf(self.tp.getNewLayerConf(dst))
            ##if a lconf has not been created build a new one
            if not dst.getLayerConf().exists():
                self.tp.initLayerConfig(src.getCapabilities(),dst,src.pxy)
        else:
            dst = None
        return src,dst
    
    def initKeywords(self):
        self.setupComplete()#from LC
        self.setupReserved()#seldom changes, from GC
        self.setupAssigned()#diff of the above 2
        
    def setupComplete(self):
        '''Reads a reduced lconf from file/table as a Nx3 array'''
        #these are all the keywords in the local file. if no dest has been set returns empty
        self.complete = self.dst.getLayerConf().getLConfAs3Array() if self.dst else []
    
    def setupReserved(self):
        '''Read the capabilities doc (as json) for reserved words'''
        #these are all the keywords LDS currently knows about            
        self.reserved = set()
        for i in [l[2] for l in self.vlayers]:
        #for i in [l[3] for l in json.loads(self.tp.parseCapabilitiesDoc(self.src.getCapabilities(),'json',self.src.pxy))]:
            self.reserved.update(set(i))
            
    def setupAssigned(self):
        '''Read the complete config doc for all keywords and diff out reserved. Requires init of complete and reserved'''   
        #these are the difference between saved and LDS-known keywords therefore, the ones the user has saved or LDS has forgotten about 
        assigned = set() 
        for i in [x[2] for x in self.complete]:
            assigned.update(set(i))
        assigned.difference_update(self.reserved)
        
        self.assigned = self.deleteForgotten(assigned)
        
    def deleteForgotten(self,alist,flt='v_\w{8}_wxs_\w{4}'):
        '''Removes keywords with the format v_########_wxs_#### since these are probably not user generated and 
        because they're used as temporary keys and will eventually be forgotten by LDS'''
        #HACK
        return set([a for a in alist if not re.search(flt,a)])
    
    def getValidLayers(self,dest=True):
        #if dest is true we should have a layerconf so use intersect(read_lc,lds_getcaps)
        capabilities = self.src.getCapabilities()
        self.tp.initCapsDoc(capabilities, self.src)
        vlayers = self.tp.assembleLayerList(self.dst,dest)
        #In the case where we are setting up unconfigured (first init) populate the layer list with default/all layers
        return vlayers if vlayers else self.tp.assembleLayerList(self.dst,intersect=False) 
    
    def buildLGList(self,groups=None,layers=None):
        '''Sets the values displayed in the Layer/Group combo'''
        #self.lgcombo.addItems(('',TransferProcessor.LG_PREFIX['g']))
        self.lglist = []
        #              lorg,value,display
        for g in sorted(groups if groups else self.assigned):
            self.lglist += ((LORG.GROUP,g.strip(),'{} (group)'.format(g.strip())),)
        for l in sorted(layers if layers else self.vlayers):
            self.lglist += ((LORG.LAYER,l[0],'{} ({})'.format(l[1],l[0])),)
        
    
    def getLGIndex(self,dispval,col=2):
        '''Finds a matching group/layer entry from its displayed name'''
        #0=lorg,1=value,2=display 
        if not LDSUtilities.mightAsWellBeNone(dispval):
            ldslog.warn('No attempt made to find index for empty group/layer request, "{}"'.format(dispval))
            return None# or 0?
            
        try:
            index = [i[col] for i in self.lglist].index(str(dispval))
        except ValueError as ve:
            ldslog.warn('Cannot find an index in column {} for the requested group/layer, "{}", from {} layers. Returning None index'.format(col,dispval,len(self.lglist)))
            index = None
        return index
    