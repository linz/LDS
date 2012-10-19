'''
v.0.0.1

LDSIncremental -  LDS Incremental Utilities

Copyright 2011 Crown copyright (c)
Land Information New Zealand and the New Zealand Government.
All rights reserved

This program is released under the terms of the new BSD license. See the 
LICENSE file for more information.

Created on 26/07/2012

@author: jramsay
'''

import logging
import os

from datetime import datetime 

from DataStore import DataStore

from LDSDataStore import LDSDataStore
from LDSUtilities import LDSUtilities, ConfigInitialiser
#from ArcSDEDataStore import ArcSDEDataStore
#from CSVDataStore import CSVDataStore
from FileGDBDataStore import FileGDBDataStore
#from ShapefileDataStore import ShapefileDataStore
#from MapinfoDataStore import MapinfoDataStore
from PostgreSQLDataStore import PostgreSQLDataStore
from MSSQLSpatialDataStore import MSSQLSpatialDataStore
from SpatiaLiteDataStore import SpatiaLiteDataStore

from ReadConfig import LayerFileReader

ldslog = logging.getLogger('LDS')


class InputMisconfigurationException(Exception): pass


class TransferProcessor(object):
    '''Primary class controlling data transfer objects and the parameters for these'''

    def __init__(self,ly=None,gp=None,ep=None,fd=None,td=None,sc=None,dc=None,cql=None,uc=None):
        #ldsu? lnl?
        #self.src = LDSDataStore() 
        #self.lnl = LDSDataStore.fetchLayerNames(self.src.getCapabilities())
        
        #do an incremental copy unless requested otherwise
        self.setIncremental()
        
        #only do a config file rebuild if requested
        self.clearInitConfig()
        
        self.group = None
        if gp != None:
            self.group = gp
            
        self.epsg = None
        if ep != None:
            self.epsg = ep
            
        self.fromdate = None
        if fd != None:
            self.fromdate = fd
        
        self.todate = None
        if td != None:
            self.todate = td     
        
        self.layer = None
        if ly != None:
            self.layer = ly  
            
        self.source_str = None
        if sc != None:
            self.source_str = sc     
            
        self.destination_str = None
        if dc != None:
            self.destination_str = dc   
            
        self.cql = None
        if cql != None:
            self.cql = cql     
            
        self.user_config = None
        if uc != None:
            self.user_config = uc   

    #incr flag copied straight from Datastore
    def setIncremental(self):
        self.INCR = True
         
    def clearIncremental(self):
        self.INCR = False
         
    def getIncremental(self):
        return self.INCR
    
    #initilaise config flags
    def setInitConfig(self):
        self.INITCONF = True
         
    def clearInitConfig(self):
        self.INITCONF = False
         
    def getInitConfig(self):
        return self.INITCONF
    
    
    
    def processLDS2PG(self):
        '''process LDS to PG convenience method'''
        self.processLDS(PostgreSQLDataStore(self.destination_str,self.user_config))
        
    def processLDS2MSSQL(self):
        '''process LDS to PG convenience method'''
        self.processLDS(MSSQLSpatialDataStore(self.destination_str,self.user_config))
        
    def processLDS2SpatiaLite(self):
        '''process LDS to SpatiaLite convenience method'''
        self.processLDS(SpatiaLiteDataStore(self.destination_str,self.user_config))
        
    def processLDS2FileGDB(self):
        '''process LDS to FileGDB convenience method'''
        self.processLDS(FileGDBDataStore(self.destination_str,self.user_config))
        
#    def processLDS2Shape(self):
#        '''process LDS to ESRI Shapefile convenience method'''
#        self.processLDS(ShapefileDataStore())
#        
#    def processLDS2Mapinfo(self):
#        '''process LDS to Mapinfo MIF convenience method'''
#        self.processLDS(MapinfoDataStore())
#        
#    def processLDS2CSV(self):
#        print "*** testing only ***"
#        self.processLDS(CSVDataStore())
#           
#    def processLDS2ArcSDE(self):
#        print "*** testing only ***"
#        self.processLDS(ArcSDEDataStore())
        

        
    def processLDS(self,dst):
        '''Process with LDS as a source and the destination supplied as an argument.
        
        The logic here is:
        
        if layer is not specified, do them all {$layer = All}
        else if layer specified do that layer {$layer = L[i]}
        
        if dates specified as 'ALL' do full replication on $layer
        else if (both) dates are specified do incr on this range for $layer
        else do auto-increment on $layer (where auto picks last-mod and current dates as range)
        '''
        
        #NB self.cql <- commandline, self.src.cql <- ldsincr.conf, 
        PREFIX = 'v:x'
        
        fdate = None
        tdate = None
        
        fname = dst.DRIVER_NAME.lower()+".layer.properties"
        
        self.dst = dst
        self.dst.setSRS(self.epsg)
        #might as well initds here, its going to be needed eventually
        self.dst.ds = self.dst.initDS(self.dst.destinationURI(DataStore.LDS_CONFIG_TABLE))
        
        self.src = LDSDataStore(self.source_str,self.user_config)
        
        #init a new DS for the DST to read config table (not needed for config file...)
        #because we need to read a new config from the SRC and write it to the DST config both of these must be initialised
        self.dst.setupLayerConfig()
        if self.getInitConfig():
            uri = self.src.getCapabilities()
            xml = LDSDataStore.readDocument(uri)
            if dst.isConfInternal():
                res = ConfigInitialiser.buildConfiguration(xml,'json')
                #open the internal layer table and populate with res 
                self.dst.buildConfigLayer(str(res))
            else:
                res = ConfigInitialiser.buildConfiguration(xml,'file')
                #open and write res to the external layer config file
                open(os.path.join(os.path.dirname(__file__), '../',fname),'w').write(str(res))
                
        if dst.isConfInternal():
            #set the layerconf to access functions (which just happen to be in the DST)
            self.dst.layerconf = self.dst
        else:
            #set the layerconf to a reader that accesses the external file
            self.dst.layerconf = LayerFileReader(fname)
        
            
        #full LDS layer name list
        lds_full = LDSDataStore.fetchLayerNames(self.src.getCapabilities())
        #list of configured layers
        lds_read = self.dst.layerconf.getLayerNames()
        
        lds_valid = map(lambda x: x.lstrip(PREFIX),set(lds_full).intersection(set(lds_read)))
        
        #Filter by group designation

        self.lnl = ()
        if self.group is not None:
            lg = set(self.group.split(','))
            for lid in lds_valid:
                if set(self.dst.layerconf.readLayerProperty(PREFIX+lid,'categories').split(',')).intersection(lg):
                    self.lnl += (lid,)
        else:
            self.lnl = lds_valid
        
        #override config file dates with command line dates if provided
        ldslog.debug("AllLayer={}, ConfLayers={}, GroupLayers={}".format(len(lds_full),len(lds_read),len(self.lnl)))
        ldslog.debug("Layer List:"+str(self.lnl))
        
        
        if self.todate is not None:
            if LDSUtilities.checkDateFormat(self.todate):
                tdate = self.todate
            else:
                raise InputMisconfigurationException("To-Date provided but format incorrect {-td yyyy-MM-dd[Thh:mm:ss]}")
        
        if self.fromdate is not None:
            if LDSUtilities.checkDateFormat(self.fromdate):
                fdate = self.fromdate
            else:
                raise InputMisconfigurationException("From-Date provided but format incorrect {-fd yyyy-MM-dd[Thh:mm:ss}")
        
        if self.layer is None:
            layer = 'ALL'  
        elif LDSUtilities.checkLayerName(self.layer):
            layer = self.layer
        else:
            raise InputMisconfigurationException("Layer name provided but format incorrect {-l v:x###}")
        
        
        '''if any date is 'ALL' full rep otherwise do auto unless we have proper dates'''
        if self.getIncremental():#fdate=='ALL' or tdate=='ALL': 
            ldslog.info("Full Replicate on "+str(layer))
            self.fullReplicate(layer)
        elif fdate is None or tdate is None:
            '''do auto incremental'''
            ldslog.info("Auto Incremental on "+str(layer)) 
            self.autoIncrement(layer)
        else:
            '''do requested date range'''
            ldslog.info("Selected Replicate on "+str(layer)+" : "+str(fdate)+" to "+str(tdate))
            self.definedIncremental(layer,fdate,tdate)

        #missing case is; if one date provided and other sg ? caught by elif (consider using the valid date?)
    
    #----------------------------------------------------------------------------------------------
    
    def fullReplicate(self,layer):
        '''Replicate across the whole date range'''
        if layer is 'ALL':
            #layer should never be none... 'ALL' needed
            #TODO consider driver reported layer list
            for layer_i in self.lnl:
                self.fullReplicateLayer(layer_i)
        else:
            self.fullReplicateLayer(layer)


    def fullReplicateLayer(self,layer):
        '''Replicate the requested layer non-incrementally'''
        self.src.read(          self.src.sourceURI(layer))
        self.dst.write(self.src,self.dst.destinationURI(layer))
        '''repeated calls to getcurrent is kinda inefficient but depending on processing time may vary by layer
        Retained since dates may change between successive calls depending on the start time of the process'''
        self.dst.setLastModified(layer,self.dst.getCurrent())
    
    
    
    def autoIncrement(self,layer):
        '''Auto-Increment reads last-mod and current time to construct incremental date ranges'''
        if layer is 'ALL':
            for layer_i in self.lnl:
                self.autoIncrementLayer(layer_i)
        else:
            self.autoIncrementLayer(layer)
            
                      
    def autoIncrementLayer(self,layer_i):
        '''For a specified layer read date ranges and call incremental'''
        fdate = self.dst.layerconf.readLayerProperty(layer_i,'lastmodified')
        if fdate is None or fdate == '':
            fdate = DataStore.EARLIEST_INIT_DATE
        tdate = self.dst.getCurrent()
        
        self.definedIncremental(layer_i,fdate,tdate)

    
    def definedIncremental(self,layer_i,fdate,tdate):
        '''Making sure the date ranges are sequential, read/write and set last modified'''
        #Once an individual layer has been defined...
        croplayer = LDSUtilities.cropChangeset(layer_i)
        #Filters are set on the SRC since theyre build into the URL, they are however specified per DST    
        self.src.setFilter(LDSUtilities.precedence(self.cql,self.dst.getFilter(),self.dst.layerconf.readLayerProperty(croplayer,'cql')))
        #SRS are set in the DST since the conversion takes place during the write process
        self.dst.setSRS(LDSUtilities.precedence(self.epsg,self.dst.getSRS(),self.dst.layerconf.readLayerProperty(croplayer,'epsg')))
        
        if datetime.strptime(tdate,'%Y-%m-%dT%H:%M:%S') > datetime.strptime(fdate,'%Y-%m-%dT%H:%M:%S'):
            #Set Incremental determines whether we use the incremental or full endpoint construction
            self.src.setIncremental()
            self.src.read(self.src.sourceURI_incrd(layer_i,fdate,tdate))
            self.dst.write(self.src,self.dst.destinationURI(layer_i))
            self.dst.setLastModified(layer_i,tdate)
        else:
            ldslog.info("No update required for layer "+layer_i+" since [start:"+fdate+" > finish:"+tdate+"]")
        return tdate
    
    

