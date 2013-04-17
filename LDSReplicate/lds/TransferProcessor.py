'''
v.0.0.1

LDSReplicate -  TransferProcessor

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
from DataStore import ASpatialFailureException

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

from ReadConfig import LayerFileReader, LayerDSReader

ldslog = logging.getLogger('LDS')


class InputMisconfigurationException(Exception): pass
class PrimaryKeyUnavailableException(Exception): pass
class LayerConfigurationException(Exception): pass
class DatasourceInitialisationException(Exception): pass


class TransferProcessor(object):
    '''Primary class controlling data transfer objects and the parameters for these'''
    
    #Hack for testing, these layers that {are too big, dont have PKs} crash the program so we'll just avoid them. Its not definitive, just ones we've come across while testing
    #1029 has no PK though Koordinates are working on this
    ###layers_that_crash = map(lambda s: 'v:x'+s, ('772','839','1029','817'))
    
    
    #Hack. To read 64bit integers we have to translate tables without GDAL's driver copy mechanism. 
    #Step 1 is to flag using feature-by-feature copy (featureCopy* instead of driverCopy)
    #Step 2 identify tables where 64 bit ints are used
    #Step 3 intercept feature build and copy and overwrite with string values
    #The tables listed below are ASP tables using a sufi number which is 64bit 
    ###layers_with_64bit_ints = map(lambda s: 'v:x'+s, ('1203','1204','1205','1028','1029'))
    #Note. This won't work for any layers that don't have a primary key, i.e. Topo and Hydro. Since feature ids are only used in ASP this shouldnt be a problem
    
    LP_SUFFIX = ".layer.properties"
    
    def __init__(self,ly=None,gp=None,ep=None,fd=None,td=None,sc=None,dc=None,cql=None,uc=None,ie=None,fbf=None):
        #ldsu? lnl?
        self.CLEANCONF = None
        self.INITCONF = None
        self.INCR = None
        
        self.src = None
        self.dst = None 
        self.lnl = None
        self.partitionlayers = None
        self.partitionsize = None
        self.sixtyfourlayers = None
        self.temptable = None
        
        #self.lnl = LDSDataStore.fetchLayerNames(self.src.getCapabilities())
        
        #do a driver copy unless valid dates have been provided indicating changeset
        self.clearIncremental()
        
        #only do a config file rebuild if requested
        self.clearInitConfig()
        self.clearCleanConfig()
        
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
            #since a layer name must begin with v:x we can 
            #1. look up v:xNNN 
            #2. see if the provided name exists in the lcf and maps to a v:x number
            self.layer = ly
            
        self.source_str = None
        if sc != None:
            self.source_str = sc
            #check for dates to set incr  
            ufd = LDSUtilities.getDateStringFromURL('from',sc)
            if ufd is not None:
                ufds = ufd.group(1)
                ldslog.warn("Using 'from:' date string from supplied URL "+str(ufds))
                self.fromdate = ufds
            utd = LDSUtilities.getDateStringFromURL('to',sc)
            if utd is not None:
                utds = utd.group(1)
                ldslog.warn("Using 'to:' date string from supplied URL "+str(utds))
                self.todate = utds
                
            #if doing incremental we also need to check changeset
            if (utd is not None or ufd is not None) and not LDSUtilities.checkHasChangesetIdentifier(sc):
                raise InputMisconfigurationException("'changeset' identifier required for incremental LDS query")
            
            #all going well we can now get the layer string. This isn't optional so we just set it
            self.layer = LDSUtilities.getLayerNameFromURL(sc)
            ldslog.warn('Using layer selection from supplied URL '+str(self.layer))  
            
            
        self.destination_str = None
        if dc != None:
            self.destination_str = dc   
            
        self.cql = None
        if cql != None:
            self.cql = cql     
            
        self.user_config = None
        if uc != None:
            self.user_config = uc   
            
        #FBF should really only be used for testing
        self.FBF = None
        if fbf != None and fbf is True:
            self.setFBF()
        elif fbf != None and fbf is False:
            self.clearFBF()
            
        self.confinternal = None
        if ie != None and ie is True:
            self.setConfInternal()
        elif ie != None and ie is False:
            self.clearConfInternal()

        
    def __str__(self):
        return 'Layer:{layer}, Group:{group}, CQL:{cql}, '.format(layer=self.layer,group=self.group,cql=self.cql)
    
    #incr flag copied straight from Datastore
    def setIncremental(self):
        self.INCR = True
         
    def clearIncremental(self):
        self.INCR = False
         
    def getIncremental(self):
        return self.INCR
    
    #Feature-by-Feature flag to override incremental
    def setFBF(self):
        self.FBF = True
         
    def clearFBF(self):
        self.FBF = False
         
    def getFBF(self):
        return self.FBF
    
    #Internal/External flag to override config set option
    def setConfInternal(self):
        self.confinternal = True
         
    def clearConfInternal(self):
        self.confinternal = False
         
    def isConfInternal(self):
        return self.confinternal
    
    #initilaise config flags
    def setInitConfig(self):
        self.INITCONF = True
         
    def clearInitConfig(self):
        self.INITCONF = False
         
    def getInitConfig(self):
        return self.INITCONF 
    
    def setCleanConfig(self):
        self.CLEANCONF = True
         
    def clearCleanConfig(self):
        self.CLEANCONF = False
         
    def getCleanConfig(self):
        return self.CLEANCONF
    
    def getSixtyFour(self,testlayer):
        '''Pre check of named layers to see if they should be treated as 64bit integer containers needing int->string conversion'''
        #if self.layer in map(lambda a: 'v:x'+a, self.layers_with_64bit_ints):
        if testlayer in self.sixtyfourlayers:
            return True
        return False
    
    def doSRSConvert(self):
        '''Pre check of layer to see if an SRS conversion has been requested. NB Any entry here assumes conversion is needed, doesn't check against existing SRS'''
        return False if self.dst.getSRS() is None else True
    
    def hasPrimaryKey(self,testlayer):
        '''Reads layer conf pkey identifier. If PK is None or something, use this to decide processing type i.e. no PK = driverCopy'''
        hpk = self.dst.layerconf.readLayerProperty(testlayer,'pkey')
        if hpk is None:
            return False
        return True
    
    def initDestination(self,dstname):
        proc = {PostgreSQLDataStore.DRIVER_NAME:PostgreSQLDataStore,
                MSSQLSpatialDataStore.DRIVER_NAME:MSSQLSpatialDataStore,
                SpatiaLiteDataStore.DRIVER_NAME:SpatiaLiteDataStore,
                FileGDBDataStore.DRIVER_NAME:FileGDBDataStore
                }.get(LDSUtilities.standardiseDriverNames(dstname))
        return proc(self.destination_str,self.user_config)
    
    def editLayerConf(self,layerlist, dstname,customkey='GUI:selection'):
        '''using the available TP initialisers, setup and build a new layer config'''
        dst = self.initDestination(dstname)
        src = LDSDataStore(self.source_str,self.user_config) 
        src.applyConfigOptions()
        dst.setupLayerConfig(self.isConfInternal())
        capabilities = src.getCapabilities()
        TransferProcessor.initLayerConfig(capabilities,dst)
        #--------------------
        lconf = TransferProcessor.getLayerConf(dst)
        for layer in layerlist:
            v1 = lconf.readLayerProperty(layer, 'category')
            v2 = v1+","+str(customkey)
            lconf.writeLayerProperty(layer, 'category', v2)    
        
        
#    def processLDS2PG(self):
#        '''process LDS to PG convenience method'''
#        self.processLDS(self.initDestination('PostgreSQL'))
#        
#    def processLDS2MSSQL(self):
#        '''process LDS to PG convenience method'''
#        self.processLDS(self.initDestination('MSSQLSpatial'))
#        
#    def processLDS2SpatiaLite(self):
#        '''process LDS to SpatiaLite convenience method'''
#        self.processLDS(self.initDestination('SpatiaLite'))
#        
#    def processLDS2FileGDB(self):
#        '''process LDS to FileGDB convenience method'''
#        self.processLDS(self.initDestination('FileGDB'))
        

        
    def processLDS(self,dst):
        '''Process with LDS as a source and the destination supplied as an argument.
        
        The logic here is:
        
        if layer is not specified, do them all {$layer = All}
        else if a group is specified do the layers in that group
        else if layer specified do that layer {$layer = L[i]} (provided its in the group)
        
        ie layer>group>all
        
        if dates specified as 'ALL' do full replication on $layer
        else if (both) dates are specified do incr on this range for $layer
        else do auto-increment on $layer (where auto picks last-mod and current dates as range)
        '''
        
        #NB self.cql <- commandline, self.src.cql <- ldsincr.conf, 
        
        fdate = None
        tdate = None
        
        #fname = dst.DRIVER_NAME.lower()+self.LP_SUFFIX
        
        self.dst = dst
        self.dst.applyConfigOptions()
        
        self.dst.setSRS(self.epsg)
        #might as well initds here, its going to be needed eventually
        self.dst.ds = self.dst.initDS(self.dst.destinationURI(None))#DataStore.LDS_CONFIG_TABLE))
        
        self.dst.versionCheck()
        
        (self.sixtyfourlayers,self.partitionlayers,self.partitionsize,self.temptable) = self.dst.mainconf.readDSParameters('Misc')
        
        self.src = LDSDataStore(self.source_str,self.user_config) 
        self.src.setPartitionSize(self.partitionsize)
        self.src.applyConfigOptions()
        
        capabilities = self.src.getCapabilities()
        
        #init a new DS for the DST to read config table (not needed for config file...)
        #because we need to read a new config from the SRC and write it to the DST config both of these must be initialised
        self.dst.setupLayerConfig(self.isConfInternal())
        if self.getInitConfig():
            TransferProcessor.initLayerConfig(capabilities,dst)                
                
        self.dst.layerconf = TransferProcessor.getLayerConf(dst)
        
        if self.dst.layerconf is None:
            raise LayerConfigurationException("Cannot initialise Layer-Configuration file/table. int="+str(dst.isConfInternal()))
        
        # *** Once the layer config is initialised we can do a layer name check ***
        if self.layer is None:
            layer = 'ALL'
        else:
            layer = LDSUtilities.checkLayerName(self.dst.layerconf,self.layer)
            if layer is None:
                raise InputMisconfigurationException("Layer name provided but format incorrect. Must be; -l {"+LDSUtilities.LDS_TN_PREFIX+"#### | <Layer-Name>}")
        
        
        # *** Assuming layer check is okay it should be safe to perform operations on the layer; the first one, delete ***
        if self.getCleanConfig():
            '''clean a selected layer (once the layer conf file has been established)'''
            if self.dst._cleanLayerByRef(self.dst.ds,self.layer):
                self.dst.clearLastModified(self.layer)
            '''once a layer is cleaned don't need to continue so quit'''
            return
            
        #full LDS layer name listv:x (from LDS WFS)
        lds_full = zip(*LDSDataStore.fetchLayerInfo(capabilities))[0]
        #list of configured layers (from layer-config file/table)
        lds_read = self.dst.layerconf.getLayerNames()
        
        lds_valid = set(lds_full).intersection(set(lds_read))
        
        #Filter by group designation

        if LDSUtilities.mightAsWellBeNone(self.group) is not None:
            self.lnl = ()
            lg = set(self.group.split(','))
            for lid in lds_valid:
                cats = self.dst.layerconf.readLayerProperty(lid,'category')
                if cats is not None and set(cats.split(',')).intersection(lg):
                    self.lnl += (lid,)
        else:
            self.lnl = lds_valid
            
            
        # ***HACK*** big layer bypass (address this with partitions)
        #self.lnl = filter(lambda l: l not in self.partitionlayers, self.lnl)
        
        #override config file dates with command line dates if provided
        ldslog.debug("AllLayer={}, ConfLayers={}, GroupLayers={}".format(len(lds_full),len(lds_read),len(self.lnl)))
        #ldslog.debug("Layer List:"+str(self.lnl))
        
        
        '''if valid dates are provided we assume copyDS'''
        if self.todate is not None:
            tdate = LDSUtilities.checkDateFormat(self.todate)
            if tdate is None:
                raise InputMisconfigurationException("To-Date provided but format incorrect {-td yyyy-MM-dd[Thh:mm:ss]}")
            else:
                self.setIncremental()
        
        if self.fromdate is not None:
            fdate = LDSUtilities.checkDateFormat(self.fromdate)
            if fdate is None:
                raise InputMisconfigurationException("From-Date provided but format incorrect {-fd yyyy-MM-dd[Thh:mm:ss}")
            else:
                self.setIncremental()       
              
        #this is the first time we use the incremental flag to do something (and it should only be needed once?)
        #if incremental is false we want a duplicate of the whole layer so fullreplicate
        if not self.getIncremental():
            ldslog.info("Full Replicate on "+str(layer)+" using group "+str(self.group))
            self.fullReplicate(layer)
        elif fdate is None or tdate is None:
            '''do auto incremental'''
            ldslog.info("Auto Incremental on "+str(layer)+" using group "+str(self.group)+" : "+str(fdate)+" to "+str(tdate)) 
            self.autoIncrement(layer,fdate,tdate)
        else:
            '''do requested date range'''
            ldslog.info("Selected Replicate on "+str(layer)+" : "+str(fdate)+" to "+str(tdate))
            self.definedIncrement(layer,fdate,tdate)

        self.dst.closeDS()
        #missing case is; if one date provided and other sg ? caught by elif (consider using the valid date?)
    
    #----------------------------------------------------------------------------------------------
    
    def fullReplicate(self,layer):
        '''Replicate across the whole date range'''
        if layer is 'ALL':
            #TODO consider driver reported layer list
            for layer_i in self.lnl:
                try:
                    self.fullReplicateLayer(str(layer_i))
                except (ASpatialFailureException, PrimaryKeyUnavailableException) as ee:
                    '''if we're processing a layer list, don't stop on an aspatial-only fault, other spatial layers might just work'''
                    ldslog.error(str(ee))
        elif layer in self.lnl:
            self.fullReplicateLayer(layer)
        else:
            ldslog.warn('Invalid layer selected, '+str(layer))


    def fullReplicateLayer(self,layer_i):
        '''Replicate the requested layer non-incrementally'''
        
        #Set filters in URI call using layer            
        self.src.setFilter(LDSUtilities.precedence(self.cql,self.dst.getFilter(),self.dst.layerconf.readLayerProperty(layer_i,'cql')))
        #SRS are set in the DST since the conversion takes place during the write process. Needed here to trigger bypass to featureCopy
        self.dst.setSRS(LDSUtilities.precedence(self.epsg,self.dst.getSRS(),self.dst.layerconf.readLayerProperty(layer_i,'epsg')))

        #while (True):
        self.src.setURI(self.src.sourceURI(layer_i))
        self.dst.setURI(self.dst.destinationURI(layer_i))
                
        #We dont try and create (=false) a DS on a LDS WFS connection since its RO
        self.src.read(self.src.getURI(),False)
        if self.src.ds is None:
            raise DatasourceInitialisationException('Unable to read from data source with URI '+self.src.getURI())
        self.dst.write(self.src,
                       self.dst.getURI(),
                       self.getIncremental() and self.hasPrimaryKey(layer_i),
                       self.getFBF(),
                       self.getSixtyFour(layer_i),
                       self.temptable,
                       self.doSRSConvert()
                    )
                  
        '''repeated calls to getcurrent is kinda inefficient but depending on processing time may vary by layer
        Retained since dates may change between successive calls depending on the start time of the process'''
        self.dst.setLastModified(layer_i,self.dst.getCurrent())
        
    
    def autoIncrement(self,layer,fdate,tdate):
        if layer is 'ALL':
            for layer_i in self.lnl:
                try:
                    self.autoIncrementLayer(str(layer_i),fdate,tdate)
                except ASpatialFailureException as afe:
                    '''if we're processing a layer list, don't stop on an aspatial-only fault'''
                    ldslog.error(str(afe))
        elif layer in self.lnl:
            self.autoIncrementLayer(layer,fdate,tdate)
        else:
            ldslog.warn('Invalid layer selected, '+str(layer))
            
    def autoIncrementLayer(self,layer_i,fdate,tdate):
        '''For a specified layer read provided date ranges and call incremental'''
        if fdate is None or fdate == '':    
            fdate = self.dst.layerconf.readLayerProperty(layer_i,'lastmodified')
            if fdate is None or fdate == '':
                fdate = DataStore.EARLIEST_INIT_DATE
                
        if tdate is None or tdate == '':         
            tdate = self.dst.getCurrent()
        
        self.definedIncrementLayer(layer_i,fdate,tdate)

    def definedIncrement(self,layer,fdate,tdate):
        '''Final check on layer validity with provided dates'''
        if layer is 'ALL':
            for layer_i in self.lnl:
                try:
                    self.definedIncrementLayer(str(layer_i),fdate,tdate)
                except (ASpatialFailureException, PrimaryKeyUnavailableException) as ee:
                    '''if we're processing a layer list, don-t stop on an aspatial-only fault'''
                    ldslog.error(str(ee))
        elif layer in self.lnl:
            self.definedIncrementLayer(layer,fdate,tdate)
        else:
            ldslog.warn('Invalid layer selected, '+str(layer))
    
        
    def definedIncrementLayer(self,layer_i,fdate,tdate):
        '''Making sure the date ranges are sequential, read/write and set last modified'''
        #Once an individual layer has been defined...
        #croplayer = LDSUtilities.cropChangeset(layer_i)
        #Filters are set on the SRC since they're built into the URL, they are however specified per DST    
        self.src.setFilter(LDSUtilities.precedence(self.cql,self.dst.getFilter(),self.dst.layerconf.readLayerProperty(layer_i,'cql')))
        #SRS are set in the DST since the conversion takes place during the write process.
        self.dst.setSRS(LDSUtilities.precedence(self.epsg,self.dst.getSRS(),self.dst.layerconf.readLayerProperty(layer_i,'epsg')))
        
        td = datetime.strptime(tdate,'%Y-%m-%dT%H:%M:%S')
        fd = datetime.strptime(fdate,'%Y-%m-%dT%H:%M:%S')
        if (td-fd).days>0:
            
            #TODO optimise
            haspk = self.hasPrimaryKey(layer_i)
            
            #using the partition layers list forces manual paging even if the WFS paging is switched on... might need to make this clearer
            if layer_i in self.partitionlayers:
                if not haspk:
                    raise PrimaryKeyUnavailableException('Cannot partition layer '+str(layer_i)+'without a valid primary key')
                self.src.setPrimaryKey(self.dst.layerconf.readLayerProperty(layer_i,'pkey'))
                self.src.setPartitionStart(0)
                self.src.setPartitionSize(self.partitionsize)#redundant, set earlier
                self.setFBF()
                
            while 1:
                #set up URI
                self.src.setURI(self.src.sourceURI_incrd(layer_i,fdate,tdate) if haspk else self.src.sourceURI(layer_i))
                self.dst.setURI(self.dst.destinationURI(layer_i))
            
                #source read from URI
                self.src.read(self.src.getURI(),False)
                #destination write the SRC to the dest URI
                maxkey = self.dst.write(self.src,
                                        self.dst.getURI(),
                                        self.getIncremental() and haspk,
                                        self.getFBF(),
                                        self.getSixtyFour(layer_i),
                                        self.temptable,
                                        self.doSRSConvert()
                                    )
                if maxkey is not None:
                    self.src.setPartitionStart(maxkey)
                else:
                    break
                
            self.dst.setLastModified(layer_i,tdate)
            
        else:
            ldslog.info("No update required for layer "+layer_i+" since [start:"+fd.isoformat()+" >= finish:"+td.isoformat()+"] by at least 1 day")
        return
    
    @classmethod
    def getLayerConf(cls,dst):
        '''Return an internal/external layerconf object'''
        # *** Decide whether to use internal or external layer config ***
        if dst.isConfInternal():
            #set the layerconf using the existing DS for common accessor functions 
            return LayerDSReader(dst)
        else:
            #set the layerconf to a reader that accesses a DS delimited external file
            return LayerFileReader(dst.DRIVER_NAME.lower()+cls.LP_SUFFIX)
            
            
    @classmethod
    def initLayerConfig(cls,capabilities,dst):
        '''class method initialising a layer config'''
        xml = LDSDataStore.readDocument(capabilities)
        if dst.isConfInternal():
            res = ConfigInitialiser.buildConfiguration(xml,'json')
            #open the internal layer table and populate with res 
            dst.buildConfigLayer(str(res))
        else:
            res = ConfigInitialiser.buildConfiguration(xml,'file')
            #open and write res to the external layer config file
            open(os.path.join(os.path.dirname(__file__), '../conf/',dst.DRIVER_NAME.lower()+cls.LP_SUFFIX),'w').write(str(res))