'''
v.0.0.1

LDSReplicate -  DataStore

Copyright 2011 Crown copyright (c)
Land Information New Zealand and the New Zealand Government.
All rights reserved

This program is released under the terms of the new BSD license. See the 
LICENSE file for more information.

DataStore is the base Datasource wrapper object 

Created on 9/08/2012

@author: jramsay
'''

import ogr
import osr
import gdal
import re
import logging
import string

#from osr import CoordinateTransformation
from datetime import datetime
from abc import ABCMeta, abstractmethod

from LDSUtilities import LDSUtilities,SUFIExtractor
from ProjectionReference import Projection
from ConfigWrapper import ConfigWrapper
#from LDSDataStore import LDSDataStore

ldslog = logging.getLogger('LDS')
#Enabling exceptions halts program on non critical errors i.e. create DS throws exception but builds valid DS anyway 
ogr.UseExceptions()

#exceptions
class DSReaderException(Exception): pass
class LDSReaderException(DSReaderException): pass
class IncompleteWFSRequestException(LDSReaderException): pass
class DriverInitialisationException(LDSReaderException): pass
class DatasourceCopyException(LDSReaderException): pass
class DatasourceCreateException(LDSReaderException): pass
class DatasourceOpenException(DSReaderException): pass
class LayerCreateException(LDSReaderException): pass
class InvalidLayerException(LDSReaderException): pass
class InvalidFeatureException(LDSReaderException): pass
class ASpatialFailureException(LDSReaderException): pass
class UnknownTemporaryDSType(LDSReaderException): pass
class MalformedConnectionString(DSReaderException): pass
class InaccessibleLayerException(DSReaderException): pass
class InaccessibleFeatureException(DSReaderException): pass


class DataStore(object):
    '''
    DataStore superclasses PostgreSQL, LDS(WFS), FileGDB and SpatiaLite datastores.
    This class contains the main copy functions for each datasource and sets up default connection parameters. Common options are also set up in this class 
    but variations are implemented in the appropriate subclasses
    '''
    __metaclass__ = ABCMeta


    LDS_CONFIG_TABLE = 'lds_config'
    DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'
    EARLIEST_INIT_DATE = '2000-01-01T00:00:00'
    #candidates for user config
    MAXIMUM_WFS_ATTEMPTS = 5
    TRANSACTION_THRESHOLD_WFS_ATTEMPTS = 4
    
    DRIVER_NAME = '<init in subclass>'
    
    CONFIG_COLUMNS = ('id','pkey','name','category','lastmodified','geocolumn','index','epsg','discard','cql')
    #TEMP_DS_TYPES = ('Memory','ESRI Shapefile','Mapinfo File','GeoJSON','GMT','DXF')
    
    ValidGeometryTypes = (ogr.wkbUnknown, ogr.wkbPoint, ogr.wkbLineString,
                      ogr.wkbPolygon, ogr.wkbMultiPoint, ogr.wkbMultiLineString, 
                      ogr.wkbMultiPolygon, ogr.wkbGeometryCollection, ogr.wkbNone, 
                      ogr.wkbLinearRing, ogr.wkbPoint25D, ogr.wkbLineString25D,
                      ogr.wkbPolygon25D, ogr.wkbMultiPoint25D, ogr.wkbMultiLineString25D, 
                      ogr.wkbMultiPolygon25D, ogr.wkbGeometryCollection25D)
    
    
    def __init__(self,conn_str=None,user_config=None):
        '''
        Constructor inits driver and some date specific settings. Arguments are for config overrides 
        '''

        #PYLINT. Set by TP but defined here. Not sure I agree with this requirement since it enforces specific instantiation order
        self.layer = None
        self.layerconf = None
        self.OVERWRITE = None
        self.driver = None
        self.uri = None
        self.cql = None
        self.srs = None
        self.config = None
        self.src_link = None
        self.sufi_list = None
        self.ds = None
        self.transform = None
        self.sixtyfour = None
        self.conn_str = None
        
        self.CONFIG_XSL = "getcapabilities."+self.DRIVER_NAME.lower()+".xsl"
         
        if LDSUtilities.mightAsWellBeNone(conn_str) is not None:
            self.conn_str = conn_str
        
        self.setSRS(None)
        self.setFilter(None)     

        self.setOverwrite()
        
        self.getDriver(self.DRIVER_NAME)
        #NB. mainconf here isnt the same as the main/user distinction in the ConfigWrapper    
        self.mainconf = ConfigWrapper(user_config)
        
        self.params = self.mainconf.readDSParameters(self.DRIVER_NAME)
        
        '''set of <potential> columns not needed in final output, global'''
        self.optcols = set(['__change__','gml_id'])
        
     
    def applyConfigOptions(self):
        for opt in self.getConfigOptions():
            ldslog.info('Applying '+self.DRIVER_NAME+' option; '+opt)
            k,v = str(opt).split('=')
            gdal.SetConfigOption(k.strip(),v.strip())
             
    def getDriver(self,driver_name):

        self.driver = ogr.GetDriverByName(driver_name)
        if self.driver == None:
            raise DriverInitialisationException, "Driver cannot be initialised for type "+driver_name
            

    def setURI(self,uri):
        self.uri = uri
        
    def getURI(self):
        return self.uri

    def setFilter(self,cql):
        self.cql = cql
         
    def getFilter(self):
        return self.cql
    
    def setSRS(self,srs):
        '''Sets the destination SRS EPSG code'''
        self.srs = srs
         
    def getSRS(self):
        return self.srs  
    
    def setConfInternal(self):
        self.config = True
            
    def clearConfInternal(self):
        self.config = False
         
    def isConfInternal(self):
        return self.config       
    
    #--------------------------  
    
    def setOverwrite(self):
        self.OVERWRITE = "YES"
         
    def clearOverwrite(self):
        self.OVERWRITE = "NO"
         
    def getOverwrite(self):
        return self.OVERWRITE   
    
    def getConfigOptions(self):
        '''Returns common options, overridden in subclasses for source specifc options'''
        return []    
    
    def getLayerOptions(self,layer_id):
        '''Returns common options, overridden in subclasses for source specifc options'''
        #layer_id used in some subclasses
        return ['OVERWRITE='+self.getOverwrite()]#,'OGR_ENABLE_PARTIAL_REPROJECTION=True']
    
    
    @abstractmethod
    def sourceURI(self,layer):
        '''Abstract URI method for returning source. Raises NotImplementedError if accessed directly'''
        raise NotImplementedError("Abstract method sourceURI not implemented")
    
    @abstractmethod
    def destinationURI(self,layer):
        '''Abstract URI method for returning destination. Raises NotImplementedError if accessed directly'''
        raise NotImplementedError("Abstract method destinationURI not implemented")
    
    @abstractmethod
    def validateConnStr(self,conn_str):
        '''Abstract method to check user supplied connection strings. Raises NotImplementedError if accessed directly'''
        raise NotImplementedError("Abstract method destinationURI not implemented")
    
    def initDS(self,dsn=None,create=True):
        '''Initialise the data source calling a provided DSN or self.dsn and a flag to indicate whether we should try and create a DS if none found'''
        ds = None
        '''initialise a DS for writing'''
        try:
            #we turn ogr exceptions off here so reported errors don't kill DS initialisation 
            ogr.DontUseExceptions()
            ds = self.driver.Open(LDSUtilities.percentEncode(dsn) if self.DRIVER_NAME=='WFS' else dsn, update = 1 if self.getOverwrite()=='YES' else 0)       
            if ds is None:
                raise DSReaderException("Error opening DS "+str(dsn)+(', attempting DS create.' if create else ', quitting.'))
        except (RuntimeError,DSReaderException) as dsre1:
            #print "DSReaderException",dsre1 
            ldslog.error(dsre1,exc_info=1)
            if create:
                try:
                    ds = self.driver.CreateDataSource(dsn)
                    if ds is None:
                        raise DSReaderException("Error creating DS "+str(dsn)+", quitting")
                except DSReaderException as dsre2:
                    #print "DSReaderException, Cannot create DS.",dsre2
                    ldslog.error(dsre2,exc_info=1)
                    raise
                except RuntimeError as rte:
                    '''this is only caught if ogr.UseExceptions() is enabled (which we done enable since RunErrs thrown even when DS completes)'''
                    #print "GDAL RuntimeError. Error creating DS.",rte
                    ldslog.error(rte,exc_info=1)
                    raise
            else:
                raise dsre1
        finally:
            ogr.UseExceptions()
        return ds
        
    def read(self,dsn,create=True):
        '''Main DS read method'''
        ldslog.info("DS read "+dsn)#.split(":")[0])
        #5050 initDS for consistency and utilise if-ds-is-none check OR quick open and overwrite
        self.ds = self.initDS(dsn,create)
        #self.ds = self.driver.Open(dsn)
    
    def write(self,src,dsn,incr_haspk,fbf,sixtyfour,temptable,srsconv):
        '''Main DS write method. Attempts to open or alternatively, create a datasource'''

        #mild hack. src_link created so we can re-query the source as a doc to get 64bit ints as strings
        self.src_link = src
        #we need to store 64 beyond fC/dC flag to identify need for sufi-to-str conversion
        self.sixtyfour = sixtyfour
        max_key = None
        self.attempts = 0
        
        while self.attempts < self.MAXIMUM_WFS_ATTEMPTS:
            try:
                #if incr&haspk then fCi
                if incr_haspk:
                    # standard incremental featureCopyIncremental. change_col used in delete list and as change (INS/DEL/UPD) indicator
                    max_key = self.featureCopyIncremental(src.ds,self.ds,src.CHANGE_COL)
                else:
                    max_key = self.featureCopy(src.ds,self.ds)
        #        #if not(incr&haspk) & 64b attempt fC
        #        elif sixtyfour or srsconv or fbf or DONT_USE_DIRECT_COPY:
        #            #do a featureCopy* if override asks or if a table has big ints
        #            max_key = self.featureCopy(src.ds,self.ds)
        #        else:
        #            # no cols to delete and no operational instructions, just duplicate. No good for partition copying since entire layer is specified
        #            self.driverCopy(src.ds,self.ds,temptable) 
    
            except RuntimeError as rte:
                import gdal
                em = gdal.GetLastErrorMsg()
                en = gdal.GetLastErrorNo()
                ldslog.warn("ErrorMsg: "+str(em))
                ldslog.warn("ErrorNo: "+str(en))
                #Errors below seem to all indicate server load problems, so we try again
                if self.attempts < self.MAXIMUM_WFS_ATTEMPTS-1 and ( \
                    re.search(   'HTTP error code : 504',str(rte)) \
                    or re.search('HTTP error code : 502',str(rte)) \
                    or re.search('HTTP error code : 404',str(rte)) \
                    or re.search('General Error',str(rte)) \
                    or re.search('Empty content returned by server',str(rte))):
                    self.attempts += 1
                    attcount = str(self.attempts)+"/"+str(self.MAXIMUM_WFS_ATTEMPTS)
                    ldslog.warn("Failed LDS fetch attempt "+attcount+". "+str(rte))
                    print '*** Att '+attcount+'  *** '+str(datetime.now().isoformat())
                    #re-initialise one/all of the datasources
                    src.read(src.getURI(),False)
                    #self.read(self.getURI(),False)
                    
                else: 
                    ldslog.error(rte,exc_info=1)
                    raise
            else:
                break
            
        return max_key
        
    def closeDS(self):
        '''close a DS with sync and destroy'''
        ldslog.info("Sync DS and Close")
        self.ds.SyncToDisk()
        self.ds.Destroy()  
              
    def driverCopy(self,src_ds,dst_ds,temptable):
        '''Copy from source to destination using the driver copy and without manipulating data'''       
        from TemporaryDataStore import TemporaryDataStore
        
        ldslog.info("Using driverCopy. Non-Incremental driver copy")
        for li in range(0,src_ds.GetLayerCount()):
            src_layer = src_ds.GetLayer(li)
            src_info = LayerInfo(LDSUtilities.cropChangeset(src_layer.GetName()))
            
            #ref_name = self.layerconf.readConvertedLayerName(src_layer_name)
            #(ref_pkey,ref_name,ref_group,ref_gcol,ref_index,ref_epsg,ref_lmod,ref_disc,ref_cql) = self.layerconf.readLayerParameters(src_layer_name)
            layerconfentry = self.layerconf.readLayerParameters(src_info.layer_id)
            
            dst_info = LayerInfo(src_info.layer_id,self.generateLayerName(layerconfentry.name))
            self.optcols |= set(layerconfentry.disc.strip('[]{}()').split(',') if all(i in string.whitespace for i in layerconfentry.disc) else [])
            
            try:
                #TODO test on MSSQL since schemas sometimes needed ie non dbo
                dst_ds.DeleteLayer(dst_info.layer_id)          
            except ValueError as ve:
                ldslog.warn("Cannot delete layer "+dst_info.layer_id+". It probably doesn't exist. "+str(ve))
                

            try:
                if temptable == 'DIRECT':                    
                    layer = dst_ds.CopyLayer(src_layer,dst_info.layer_id,self.getLayerOptions(src_info.layer_id))
                    self.deleteOptionalColumns(layer)
                elif temptable in TemporaryDataStore.TEMP_MAP.keys():
                    tds = TemporaryDataStore.getInstance(temptable)()
                    tds_ds = tds.initDS()
                    tds_layer = tds_ds.CopyLayer(src_layer,dst_info.layer_id,[])
                    tds.deleteOptionalColumns(tds_layer)
                    layer = dst_ds.CopyLayer(tds_layer,dst_info.layer_id,self.getLayerOptions(src_info.layer_id))
                    #tds_ds.SyncToDisk()
                    tds_ds.Destroy()  
                else:
                    ldslog.error('Cannot match DS type "'+str(temptable)+'" with known types '+str(TemporaryDataStore.TEMP_MAP.keys()))
                    raise UnknownTemporaryDSType('Cannot match DS type "'+str(temptable)+'" with known types '+str(TemporaryDataStore.TEMP_MAP.keys()))
            except RuntimeError as rte:
                if 'General function failure' in str(rte):
                    #GFF usually indicates a driver copy error (FGDB)
                    ldslog.error('GFF on driver copy. Recommend upgrade to GDAL > 1.9.2')
                else:
                    raise

            #if the copy succeeded we now need to build an index and delete unwanted columns so get the new layer     
            #layer = dst_ds.GetLayer(dst_layer_name)
            if layer is None:
                # **HACK** the only way to get around driver copy failures seems to be by doing a feature-by-feature featureCopyIncremental and changing the sref 
                ldslog.error('Layer not created, attempting feature-by-feature copy')
                return self.featureCopyIncremental(src_ds,dst_ds,None)

            if layerconfentry.index is not None:
                self.buildIndex(layerconfentry,dst_info.layer_name)
            
        return
    
        
    def deleteOptionalColumns(self,dst_layer):
        '''Delete unwanted columns from layer'''
        #because column deletion behaviour is different for each driver (advancing index or not) split out and subclass
        dst_layer_defn = dst_layer.GetLayerDefn()
        #loop layer fields and discard the unwanted columns
        offset = 0
        for fi in range(0,dst_layer_defn.GetFieldCount()):
            fdef = dst_layer_defn.GetFieldDefn(fi-offset)
            fdef_nm = fdef.GetName()
            #print '>>>>>',fi,fi-offset,fdef_nm
            if fdef is not None and fdef_nm in self.optcols:
                self.deleteFieldFromLayer(dst_layer, fi-offset,fdef_nm)
                offset += 1
                
    def deleteFieldFromLayer(self,layer,field_id,fdef_nm):
        '''per DS delete field since some do not support this'''
        layer.DeleteField(field_id)

    def generateLayerName(self,ref_name):
        '''Generic layer name constructor'''
        '''Doesn't use schema prefix since its not used in FileGDB, SpatiaLite 
        and PostgreSQL implements an "active_schema" option bypassing the need for a schema declaration'''
        return self.sanitise(ref_name)
        
    #--------------------------------------------------------------------------            
    
    def featureCopy(self,src_ds,dst_ds):
        '''Feature copy without the change column (and other incremental) overhead. Replacement for driverCopy(cloneDS).''' 
        for li in range(0,src_ds.GetLayerCount()):
            new_layer = False
            src_layer = src_ds.GetLayer(li)

            #TODO. resolve conflict between lastmodified and fdate
            src_info = LayerInfo(LDSUtilities.cropChangeset(src_layer.GetName()))
            
            '''retrieve per-layer settings from props'''
            #(ref_pkey,ref_name,ref_group,ref_gcol,ref_index,ref_epsg,ref_lmod,ref_disc,ref_cql) = self.layerconf.readLayerParameters(src_layer_name)
            layerconfentry = self.layerconf.readLayerParameters(src_info.layer_id)
            
            dst_info = LayerInfo(src_info.layer_id,self.generateLayerName(layerconfentry.name))
            
            ldslog.info("Dest layer: "+dst_info.layer_id)
            
            '''parse discard columns'''
            self.optcols |= set(layerconfentry.disc.strip('[]{}()').split(',') if layerconfentry.disc is not None else [])

            ldslog.warning("Non-Incremental layer ["+dst_info.layer_id+"] request. (re)Creating layer")
            '''create a new layer if a similarly named existing layer can't be found on the dst'''
            src_info.spatial_ref = src_layer.GetSpatialRef()
            src_info.geometry = src_layer.GetGeomType()
            src_info.layer_defn = src_layer.GetLayerDefn()
            #transforms from SRC to DST sref if user requests a different EPSG, otherwise SRC returned unchanged
            dst_info.spatial_ref = self.transformSRS(src_info.spatial_ref)
            
            (dst_layer,new_layer) = self.buildNewDataLayer(dst_info,src_info,dst_ds)
                

            if self.attempts < self.TRANSACTION_THRESHOLD_WFS_ATTEMPTS:
                dst_layer.StartTransaction()
            else:
                ldslog.warn('FBF outside transaction')
                
            #add/copy features
            #src_layer.ResetReading()
            src_feat = src_layer.GetNextFeature()

            '''since the characteristics of each feature wont change between layers we only need to define a new feature definition once'''
            if src_feat is not None:
                new_feat_def = self.partialCloneFeatureDef(src_feat)
                
            while src_feat is not None:
                #slowest part of this copy operation is the insert since we have to build a new feature from defn and check fields for discards and sufis
                self.insertFeature(dst_layer,src_feat,new_feat_def)
                
                src_feat = src_layer.GetNextFeature()
            
            '''Builds an index on a newly created layer if; 
            1) new layer flag is true, 2) index p|s is asked for, 3) we have a pk to use and 4) the layer has at least 1 feat'''
            #May need to be pushed out to subclasses depending on syntax differences
            if new_layer and layerconfentry.index is not None and layerconfentry.pkey is not None and src_feat is not None:
                self.buildIndex(layerconfentry,dst_info.layer_name)
                
            if self.attempts < self.TRANSACTION_THRESHOLD_WFS_ATTEMPTS:
                try:
                    dst_layer.CommitTransaction()
                except RuntimeError:
                    dst_layer.RollbackTransaction()
                    raise
            
            src_layer.ResetReading()
            dst_layer.ResetReading()    

    
    def featureCopyIncremental(self,src_ds,dst_ds,changecol):
        #TDOD. decide whether C_C is better as an arg or a src.prop
        '''DataStore feature-by-feature replication for incremental queries'''
        #build new layer by duplicating source layers  
        max_index = None
        ldslog.info("Using featureCopyIncremental. Per-feature copy")
        for li in range(0,src_ds.GetLayerCount()):
            new_layer = False
            src_layer = src_ds.GetLayer(li)

            #TODO. resolve conflict between lastmodified and fdate
            src_info = LayerInfo(LDSUtilities.cropChangeset(src_layer.GetName()))
            
            '''retrieve per-layer settings from props'''
            #(ref_pkey,ref_name,ref_group,ref_gcol,ref_index,ref_epsg,ref_lmod,ref_disc,ref_cql) = self.layerconf.readLayerParameters(src_layer_name)
            layerconfentry = self.layerconf.readLayerParameters(src_info.layer_id)
            
            dst_info = LayerInfo(src_info.layer_id,self.generateLayerName(layerconfentry.name))
            
                
            ldslog.info("Dest layer: "+dst_info.layer_id)
            
            '''parse discard columns'''
            self.optcols |= set(layerconfentry.disc.strip('[]{}()').split(',') if layerconfentry.disc is not None else [])
            
            try:
                dst_layer = dst_ds.GetLayer(dst_info.layer_id)
            except RuntimeError as rer:
                '''Instead of returning none, runtime errors sometimes occur if the layer doesn't exist and needs to be created'''
                ldslog.warning("Runtime Error fetching layer. "+str(rer))
                dst_layer = None
                
            if dst_layer is None:
                ldslog.warning(dst_info.layer_id+" does not exist. Creating new layer")
                '''create a new layer if a similarly named existing layer can't be found on the dst'''
                src_info.spatial_ref = src_layer.GetSpatialRef()
                src_info.geometry = src_layer.GetGeomType()
                src_info.layer_defn = src_layer.GetLayerDefn()
                dst_info.spatial_ref = self.transformSRS(src_info.spatial_ref)
                
                (dst_layer,new_layer) = self.buildNewDataLayer(dst_info,src_info,dst_ds)
                
            #dont bother with transactions if they're failing > N times
            if self.attempts < self.TRANSACTION_THRESHOLD_WFS_ATTEMPTS:
                dst_layer.StartTransaction()
            else:
                ldslog.warn('FBF outside transaction')

            
            #add/copy features
            src_feat = src_layer.GetNextFeature()
            '''since the characteristics of each feature wont change between layers we only need to define a new feature definition once'''
            if src_feat is not None:
                new_feat_def = self.partialCloneFeatureDef(src_feat)
                e = 0
                while 1:
                    '''identify the change in the WFS doc (INS,UPD,DEL)'''
                    change =  (src_feat.GetField(changecol) if LDSUtilities.mightAsWellBeNone(changecol) is not None else "insert").lower()
                    '''not just copy but possubly delete or update a feature on the DST layer'''
                    #self.copyFeature(change,src_feat,dst_layer,ref_pkey,new_feat_def,ref_gcol)
                    
                    try:
                        if change == 'insert': 
                            e = self.insertFeature(dst_layer,src_feat,new_feat_def)
                        elif change == 'delete': 
                            e = self.deleteFeature(dst_layer,src_feat,             layerconfentry.pkey)
                        elif change == 'update': 
                            e = self.updateFeature(dst_layer,src_feat,new_feat_def,layerconfentry.pkey)
                        else:
                            ldslog.error("Error with Key "+str(change)+" !E {ins,del,upd}")
                        #    raise KeyError("Error with Key "+str(change)+" !E {ins,del,upd}",exc_info=1)
                    except InvalidFeatureException as ife:
                        ldslog.error("Invalid Feature Exception during "+change+" operation on dest. "+str(ife),exc_info=1)
                        
                    if e != 0:                  
                        ldslog.error("Driver Error ["+str(e)+"] on "+change,exc_info=1)
                        if change == 'update':
                            ldslog.warn('Update failed on SetFeature, attempting delete/insert')
                            #let delete and insert error handlers take care of any further exceptions
                            e1 = self.deleteFeature(dst_layer,src_feat,layerconfentry.pkey)
                            e2 = self.insertFeature(dst_layer,src_feat,new_feat_def)
                            if e1+e2 != 0:
                                raise InvalidFeatureException("Driver Error [d="+str(e1)+",i="+str(e2)+"] on "+change)
                    
                    
                    next_feat = src_layer.GetNextFeature()
                    #On no-new-features grab the last primary key index and break
                    if next_feat is None:
                        if hasattr(self.src_link, 'pkey'):
                            #this of course assumes the layer is correctly sorted in pkey
                            max_index = src_feat.GetField(layerconfentry.pkey)
                        break
                    else:
                        src_feat = next_feat
                    

            #self._showLayerData(dst_layer)
            
            '''Builds an index on a newly created layer if; 
            1) new layer flag is true, 2) index p|s is asked for, 3) we have a pk to use and 4) the layer has at least 1 feat'''
            #May need to be pushed out to subclasses depending on syntax differences
            if new_layer and layerconfentry.index is not None and layerconfentry.pkey is not None and src_feat is not None:
                self.buildIndex(layerconfentry,dst_info.layer_name)
                
            if self.attempts < self.TRANSACTION_THRESHOLD_WFS_ATTEMPTS:
                try:
                    dst_layer.CommitTransaction()
                except RuntimeError as rer:
                    dst_layer.RollbackTransaction()
                    raise

            src_layer.ResetReading()
            dst_layer.ResetReading()
            
        #returning nothing disables manual paging    
        #return max_index          

    def transformSRS(self,src_layer_sref):
        '''Defines the transform from one SRS to another. Doesn't actually do the transformation, just defines the transformation needed.
        Requires the supplied EPSG be correct and coordinates that can be transformed'''
        self.transform = None
        selected_sref = self.getSRS()
        if LDSUtilities.mightAsWellBeNone(selected_sref) is not None:
            #if the selected SRS fails to validate assume error and flag but dont silently drop back to default
            validated_sref = Projection.validateEPSG(selected_sref)
            if validated_sref is not None:
                self.transform = osr.CoordinateTransformation(src_layer_sref, validated_sref)
                if self.transform == None:
                    ldslog.warn('Can\'t init coordinatetransformation object with SRS:'+str(validated_sref))
                return validated_sref
            else:
                ldslog.warn("Unable to validate selected SRS, epsg="+str(selected_sref))
        else:
            return src_layer_sref
                    
    
    def insertFeature(self,dst_layer,src_feat,new_feat_def):
        '''insert a new feature'''
        new_feat = self.partialCloneFeature(src_feat,new_feat_def)
        
        e = dst_layer.CreateFeature(new_feat)

        #dst_fid = new_feat.GetFID()
        #ldslog.debug("INSERT: "+str(dst_fid))
        return e
    
    def updateFeature(self,dst_layer,src_feat,new_feat_def,ref_pkey):
        '''build new feature, assign it the looked-up matching fid and overwrite on dst'''
        if ref_pkey is None:
            ref_pkey = self.getFieldNames(src_feat)
            src_pkey = self.getFieldValues(src_feat)
        else:
            src_pkey = src_feat.GetFieldAsInteger(ref_pkey)
        
        #ldslog.debug("UPDATE: "+str(src_pkey))
        #if not new_layer_flag: 
        new_feat = self.partialCloneFeature(src_feat,new_feat_def)
        dst_fid = self._findMatchingFID(dst_layer, ref_pkey, src_pkey)
        if dst_fid is not None:
            new_feat.SetFID(dst_fid)
            e = dst_layer.SetFeature(new_feat)
            
        else:
            ldslog.error("No match for FID with ID="+str(src_pkey)+" on update",exc_info=1)
            raise InvalidFeatureException("No match for FID with ID="+str(src_pkey)+" on update")
        
        return e
    
    def deleteFeature(self,dst_layer,src_feat,ref_pkey): 
        '''lookup and delete using fid matching ID of feature being deleted'''
        #naive first implementation, might/will be slow 
        if ref_pkey is None:
            ref_pkey = self.getFieldNames(src_feat)
            src_pkey = self.getFieldValues(src_feat)
        else:
            src_pkey = src_feat.GetFieldAsInteger(ref_pkey)
            
        #ldslog.debug("DELETE: "+str(src_pkey))
        dst_fid = self._findMatchingFID(dst_layer, ref_pkey, src_pkey)
        if dst_fid is not None:
            e = dst_layer.DeleteFeature(dst_fid)
        else:
            ldslog.error("No match for FID with ID="+str(src_pkey)+" on delete",exc_info=1)
            raise InvalidFeatureException("No match for FID with ID="+str(src_pkey)+" on delete")
        
        return e
        
    def getFieldNames(self,feature):  
        '''Returns the names of fields in a feature'''
        fnlist = ()
        fdr = feature.GetDefnRef()
        for i in range(0,fdr.GetFieldCount()):
            fnlist += (fdr.GetFieldDefn(i).GetName(),)
        return fnlist
    
    def getFieldValues(self,feature):  
        '''Returns field values for a feature'''
        fvlist = ()
        for i in range(0,feature.GetFieldCount()):
            fvlist += (feature.GetFieldAsString(i),)
        return fvlist
 
                      
    def buildNewDataLayer(self,dst_info,src_info,dst_ds):
        '''Constructs a new layer using another source layer as a template. This does not populate that layer'''
        #read defns of each field
        fdef_list = []
        for fi in range(0,src_info.layer_defn.GetFieldCount()):
            fdef_list.append(src_info.layer_defn.GetFieldDefn(fi))
        
        #use the field defns to build a schema since this needs to be loaded as a create_layer option
        opts = self.getLayerOptions(src_info.layer_id)
        #NB wkbPolygon = 3, wkbMultiPolygon = 6
        dst_info.geometry = ogr.wkbMultiPolygon if src_info.geometry is ogr.wkbPolygon else self.selectValidGeom(src_info.geometry)
        
        '''build layer replacing poly with multi and revert to def if that doesn't work'''
        try:
            #gs = 'GEOGCS'
            #sr = osr.SpatialReference('EPSG:4167')
            #ac = sr.GetAuthorityCode(None)
            dst_layer = dst_ds.CreateLayer(dst_info.layer_name, dst_info.spatial_ref, dst_info.geometry, opts)
        except RuntimeError as rer:
            ldslog.error("Cannot create layer. "+str(rer))
            if 'already exists' in str(rer):
                '''indicates the table has been created previously but was not returned with the getlayer command, SL does this with null geom tables'''
                #raise ASpatialFailureException('SpatiaLite driver cannot be used to update ASpatial layers')
                #NB. DeleteLayer also wont work since the layer can't be found.
                #dst_ds.DeleteLayer(dst_layer_name)
                #dst_layer = dst_ds.CreateLayer(dst_layer_name,dst_sref,src_layer_geom,opts)
                #Option 2. Deleting the layer with SQL
                self.executeSQL('drop table '+dst_info.layer_name)
                dst_layer = dst_ds.CreateLayer(dst_info.layer_name,dst_info.spatial_ref,src_info.geometry,opts)
            elif 'General function failure' in str(rer):
                ldslog.error('Possible SR problem, continuing. '+str(rer))
                dst_layer = None
            
        #if we fail through to this point most commonly the problem is SpatialRef
        if dst_layer is None:
            #overwrite the dst_sref if its causing trouble (ie GDAL general function errors)
            dst_info.spatial_ref = Projection.getDefaultSpatialRef()
            ldslog.warning("Could not initialise Layer with specified SRID {"+str(src_info.spatial_ref)+"}.\n\nUsing Default {"+str(dst_info.spatial_ref)+"} instead")
            dst_layer = dst_ds.CreateLayer(dst_info.layer_name,dst_info.spatial_ref,dst_info.geometry,opts)
                
        #if still failing, give up
        if dst_layer is None:
            ldslog.error(dst_info.layer_name+" cannot be created")
            raise LayerCreateException(dst_info.layer_name+" cannot be created")
    
        
        '''if the dst_layer isn't empty it's probably not a new layer and we shouldn't be adding stuff to it'''
        if len(dst_layer.schema)>0:
            return (dst_layer,False)
        
        '''setup layer headers for new layer etc'''
        for fdef in fdef_list:
            #print "field:",fi
            name = fdef.GetName()
            if name not in self.optcols and name not in [field.name for field in dst_layer.schema]:
                #dst_layer.CreateField(fdef)
                '''post create alter column type'''
                if self.identify64Bit(name):
                    #self.changeColumnIntToString(dst_layer_name,name)
                    new_field_def = ogr.FieldDefn(name,ogr.OFTString)
                    dst_layer.CreateField(new_field_def)
                else:
                    dst_layer.CreateField(fdef)
                    
                #could check for any change tags and throw exception if none
                
        return (dst_layer,True)
    
    def selectValidGeom(self,geom):
        '''To be overridden, eliminates geometry types that cause trouble for certain drivers'''
        return geom
                           
    def changeColumnIntToString(self,table,column):
        '''Default column type changer, to be overriden but works on PG. Used to change 64 bit integer columns to string''' 
        #NOTE. No longer used! column change done at build time
        self.executeSQL('alter table '+table+' alter '+column+' type character varying')
        
    def identify64Bit(self,name):
        '''Common 64bit column identification function (just picks out the key text 'sufi' in the column name since the 
        sufi-id is the only 64 bit data type in use. This is due to change soon with some new hydro layers being added
        that have sufi-ids which aren't 64bit...)'''
        return 'sufi' in name     
                                           
    def partialCloneFeature(self,fin,fout_def):
        '''Builds a feature using a passed in feature definition. Must still ignore discarded columns since they will be in the source'''

        fout = ogr.Feature(fout_def)

        '''Modify input geometry from P to MP'''
        fin_geom = fin.GetGeometryRef()
        if fin_geom is not None:
            #absent geom attribute indicates aspatial
            if fin_geom.GetGeometryType() == ogr.wkbPolygon:
                fin_geom = ogr.ForceToMultiPolygon(fin_geom)
                fin.SetGeometryDirectly(fin_geom)
      
            '''set Geometry transforming if needed'''
            if hasattr(self,'transform') and self.transform is not None:
                #TODO check whether this fin_geom needs to be cloned first
                try:
                    fin_geom.Transform(self.transform)
                except RuntimeError as rer:
                    if 'OGR Error' in str(rer):
                        ldslog.error('Cannot convert to requested SR. '+str(rer))
                        raise
                
            '''and then set the output geometry'''
            fout.SetGeometry(fin_geom)

        #DataStore._showFeatureData(fin)
        #DataStore._showFeatureData(fout)
        '''prepopulate any 64 replacement lists. this is done once per 64bit inclusive layer so not too intensive'''
        if self.sixtyfour and (not hasattr(self,'sufi_list') or self.sufi_list is None): 
            self.sufi_list = {}
            doc = None
            for fin_no in range(0,fin.GetFieldCount()):
                fin_field_name = fin.GetFieldDefnRef(fin_no).GetName()
                if self.identify64Bit(fin_field_name) and fin_field_name not in self.sufi_list:
                    if doc is None:
                        #fetch the GC document in GML2 format for column extraction. #TODO JSON extractor
                        doc = LDSUtilities.readDocument(re.sub('JSON|GML3','GML2',self.src_link.getURI()))
                    self.sufi_list[fin_field_name] = SUFIExtractor.readURI(doc,fin_field_name)
            
        '''populate non geometric fields'''
        fout_no = 0
        for fin_no in range(0,fin.GetFieldCount()):
            fin_field_name = fin.GetFieldDefnRef(fin_no).GetName()
            #assumes id is the PK, TODO, change to pkey reference
            if fin_field_name == 'id':
                current_id =  fin.GetField(fin_no)
            if self.sixtyfour and self.identify64Bit(fin_field_name): #in self.sixtyfour
                #assumes id occurs before sufi in the document
                #sixtyfour test first since identify could be time consuming. Luckily sufi-containing tables are small and process quite quickly                
                copy_field = self.sufi_list[fin_field_name][current_id]
                fout.SetField(fout_no, str(copy_field))
                fout_no += 1
            elif fin_field_name not in self.optcols:
                copy_field = fin.GetField(fin_no)
                fout.SetField(fout_no, copy_field)
                fout_no += 1
            
        return fout 
 
    def partialCloneFeatureDef(self,fin):
        '''Builds a feature definition ignoring optcols i.e. {gml_id, __change__} and any other discarded columns'''
        #create blank feat defn
        fout_def = ogr.FeatureDefn()
        #read input feat defn
        #fin_feat_def = fin.GetDefnRef()
        
        #loop existing feature defn ignoring column X
        for fin_no in range(0,fin.GetFieldCount()):
            fin_field_def = fin.GetFieldDefnRef(fin_no)
            fin_field_name = fin_field_def.GetName()
            if self.identify64Bit(fin_field_name): 
                new_field_def = ogr.FieldDefn(fin_field_name,ogr.OFTString)
                fout_def.AddFieldDefn(new_field_def)
            elif fin_field_name not in self.optcols:
                #print "n={}, typ={}, wd={}, prc={}, tnm={}".format(fin_fld_def.GetName(),fin_fld_def.GetType(),fin_fld_def.GetWidth(),fin_fld_def.GetPrecision(),fin_fld_def.GetTypeName())
                fout_def.AddFieldDefn(fin_field_def)
                
        return fout_def
      
    def getLastModified(self,layer):
        '''Gets the last modification time of a layer to use for incremental "fromdate" calls. This is intended to be run 
        as a destination method since the destination is the DS being modified i.e. dst.getLastModified'''
        lmd = self.layerconf.readLastModified(layer)
        if lmd is None or lmd == '':
            lmd = self.EARLIEST_INIT_DATE
        return lmd
        #return lm.strftime(self.DATE_FORMAT)
        
    def setLastModified(self,layer,newdate):
        '''Sets the last modification time of a layer following a successful incremental copy operation'''
        self.layerconf.writeLayerProperty(layer, 'lastmodified', newdate)  
        
    def clearLastModified(self,layer):
        '''Clears the last modification time of a layer following a successful clean operation'''
        self.layerconf.writeLayerProperty(layer, 'lastmodified', None)  

    def getCurrent(self):
        '''Gets the current timestamp for incremental todate calls. 
        Time format is UTC for LDS compatibility.
        NB. Because the current date is generated to build the LDS URI the lastmodified time will reflect the request time and not the layer creation time'''
        dpo = datetime.utcnow()
        return dpo.strftime(self.DATE_FORMAT)  
    
    def buildIndex(self,lce,dst_layer_name):
        '''Default index string builder for new fully replicated layers'''
        ref_index = DataStore.parseStringList(lce.index)
        if ref_index.intersection(set(('spatial','s'))) and lce.gcol is not None:
            cmd = 'CREATE INDEX {}_SK ON {}({})'.format(dst_layer_name.split('.')[-1]+"_"+lce.gcol,dst_layer_name,lce.gcol)
        elif ref_index.intersection(set(('primary','pkey','p'))):
            cmd = 'CREATE INDEX {}_PK ON {}({})'.format(dst_layer_name.split('.')[-1]+"_"+lce.pkey,dst_layer_name,lce.pkey)
        elif ref_index is not None:
            #maybe the user wants a non pk/spatial index? Try to filter the string
            clst = ','.join(ref_index)
            cmd = 'CREATE INDEX {}_PK ON {}({})'.format(dst_layer_name.split('.')[-1]+"_"+DataStore.sanitise(clst),dst_layer_name,clst)
        else:
            return
        ldslog.info("Index="+','.join(ref_index)+". Execute "+cmd)
        
        try:
            self.executeSQL(cmd)
        except RuntimeError as rte:
            if re.search('already exists', str(rte)): 
                ldslog.warn(rte)
            else:
                raise

    
    # private methods
        
    def executeSQL(self,sql):
        '''Executes arbitrary SQL on the datasource'''
        '''Tagged? private since we only want it called from well controlled methods'''
        '''TODO. step through multi line queries?'''
        retval = None
        #ogr.UseExceptions()
        ldslog.debug("SQL: "+sql)
        '''validating sql as a block acts as a sort of transaction mechanism and means we can execute the entire statement which is faster'''
        if self._validateSQL(sql):
            try:
                #cast to STR since unicode raises exception in driver 
                retval = self.ds.ExecuteSQL(str(sql))
            except RuntimeError as rex:
                ldslog.error("Runtime Error. Unable to execute SQL:"+sql+". Get Error "+str(rex),exc_info=1)
                #this can be a bad thing so we want to stop if this occurs e.g. no lds_config -> no layer list etc
                #but also indicate no problem, e.g. deleting a layer already deleted
                raise
            except Exception as ex:
                ldslog.error("Exception. Unable to execute SQL:"+sql+". Exception: "+str(ex),exc_info=1)
                #raise#often misreported, halting may be unnecessary
                
        return retval
            
    def _validateSQL(self,sql):
        '''Validates SQL against a list of allowed queries. Not trying to restrict queries here, rather catch invalid SQL'''
        '''TODO. Better validation.'''
        sql = sql.lower()
        for line in sql.split('\n'):
            #ignore comments/blanks
            if re.match('^(?:#|--)|^\s*$',line):
                continue
            #first match 'create/drop index'
            if re.match('(?:create|drop)(?:\s+spatial)?\s+index',line):
                continue
            #match 'create/drop index/table'
            if re.match('(?:create|drop)\s+(?:index|table)',line):
                continue
            #match 'select'
            if re.match('select\s+(?:\w+|\*)\s+from',line):
                continue
            if re.match('select\s+(version|postgis_full_version|@@version)',line):
                continue
            #match 'insert'
            if re.match('(?:update|insert)\s+(?:\w+|\*)\s+',line):
                continue
            if re.match('if\s+object_id\(',line):
                continue
            #MSSQL insert identity flag
            if re.match('set\s+identity_insert',line):
                continue
            #match 'alter table'
            if re.match('alter\s+table',line):
                continue
            
            ldslog.error("Line in SQL failed to validate. "+line)
            return False
        
        return True
        
    def _cleanLayerByIndex(self,ds,layer_i):
        '''Deletes a layer from the DS using the DS sequence number. Not tested!'''
        ldslog.info("DS clean (ds_seq)")
        try:
            ds.DeleteLayer(layer_i)
        except ValueError as ve:
            ldslog.error('Error deleting layer with index '+str(layer_i)+'. '+str(ve))
            #since we dont want to alter lastmodified on failure
            return False
        return True
    
    def _cleanLayerByRef(self,ds,layer):
        '''Deletes a layer from the DS using the layer reference ie. v:x###'''

        #when the DS is created it uses (PG) the active_schema which is the same as the layername schema.
        #since getlayerX returns all layers in all schemas we ignore the ones with schema prepended since they wont be 'active'
        name = self.generateLayerName(self.layerconf.readLayerProperty(layer,'name')).split('.')[-1]
        try:
            for li in range(0,self.ds.GetLayerCount()):
                lref = ds.GetLayerByIndex(li)
                lname= lref.GetName()
                if lname == name:
                    ds.DeleteLayer(li)
                    ldslog.info("DS clean "+str(lname))
                    #since we only want to alter lastmodified on success return flag=True
                    #we return here too since we assume user only wants to delete one layer, re-indexing issues occur for more than one deletion
                    return True
            ldslog.warning('Matching layer name not found, '+name+'. Attempting base level delete.')
            try:
                self._baseDeleteLayer(name)
            except:
                raise DatasourceOpenException('Unable to clean layer, '+str(layer))
            return True
                
                    
        except ValueError as ve:
            ldslog.error('Error deleting layer '+str(layer)+'. '+str(ve))
            raise
        except Exception as e:
            ldslog.error("Generic error in layer "+str(layer)+' delete. '+str(e))
            raise
        return False
    
    def _baseDeleteLayer(self,table):
        '''Basic layer delete function intended for aspatial tables which are not returned by queries to the DS. Should work on most DS types'''
        #TODO. Implement for all DS types
        sql_str = "drop table "+table
        return self.executeSQL(sql_str)    
    
    def _baseDeleteColumn(self,table,column):
        '''Basic column delete function for when regular deletes fail. Intended for aspatial tables which are not returned by queries to the DS'''
        #TODO. Implement for all DS types
        sql_str = "alter table "+table+" drop column "+column
        return self.executeSQL(sql_str)
        
    def _clean(self):
        '''Deletes the entire DS layer by layer'''
        #for PG, indices decrement as layers are deleted so delete i=0, N times
        for li in range(0,self.ds.GetLayerCount()):
            if self._cleanLayerByIndex(self.ds,0):
                self.clearLastModified(li)
        
    def _findMatchingFID(self,search_layer,ref_pkey,key_val):
        '''Find the FID matching a primary key value'''
        if isinstance(ref_pkey,basestring):
            newf = self._findMatchingFeature(search_layer,ref_pkey,key_val)
        else:
            newf = self._findMatchingFeature_AllFields(search_layer,ref_pkey,key_val)
        if newf is None:
            return None
        return newf.GetFID()
    
    def _findMatchingFeature_AllFields(self,search_layer,col_list,row_vals):
        '''
        find a feature for a layer with no PK, to do this generically we have to query all fields'''
        qt = ()
        for col,val in zip(col_list,row_vals):
            if col not in self.optcols and val is not '':
                qt += (str(col)+" = '"+str(val)+"'",)        
        search_layer.SetAttributeFilter(' and '.join(qt).replace("''","'"))
        #ResetReading to fix MSSQL ODBC bug, "Function Sequence Error"  
        search_layer.ResetReading()
        return search_layer.GetNextFeature()
           
    def _findMatchingFeature(self,search_layer,ref_pkey,key_val):
        '''Find the Feature matching a primary key value'''
        qry = ref_pkey+" = '"+str(key_val)+"'"
        search_layer.SetAttributeFilter(qry)
        #ResetReading to fix MSSQL ODBC bug, "Function Sequence Error"  
        search_layer.ResetReading()
        return search_layer.GetNextFeature()
            
            
            
# static utility methods
    
    @staticmethod
    def sanitise(name):
        '''Manually substitute potential table naming errors implemented as a common function to retain naming convention across all outputs.
        No guarantees are made that this feature won't cause naming conflicts e.g. A-B-C -> a_b_c <- a::{b}::c'''
        #append _ to name beginning with a number
        if re.match('\A\d',name):
            name = "_"+name
        #replace unwanted chars with _ and compress multiple and remove trailing
        sanitised = re.sub('_+','_',re.sub('[ \-,.\\\\/:;{}()\[\]]','_',name.lower())).rstrip('_')
        #unexpected name substitutions can be a source of bugs, log as debug
        ldslog.debug("Sanitise: raw="+name+" name="+sanitised)
        return sanitised
    
    @staticmethod
    def parseStringList(st):
        '''QaD List-as-String to List parser'''
        return set(st.lower().rstrip(')]}').lstrip('{[(').split(','))
    
    # debugging methods
    
    @staticmethod
    def _showFeatureData(feature):
        '''Prints feature/fid info. Useful for debugging'''
        ldslog.debug("Feat:FID:"+str(feature.GetFID()))
        ldslog.debug("Feat:Geom:"+str(feature.GetGeometryRef().GetGeometryType()))
        for field_no in range(0,feature.GetFieldCount()):
            ldslog.debug("fid={},fld_no={},fld_data={}".format(feature.GetFID(),field_no,feature.GetFieldAsString(field_no)))
            
    @staticmethod
    def _showLayerData(layer):
        '''Prints layer and embedded feature data. Useful for debugging'''
        ldslog.debug("Layer:Name:"+layer.GetName())
        layer.ResetReading()
        feat = layer.GetNextFeature()
        while feat is not None:
            DataStore._showFeatureData(feat)
            feat = layer.GetNextFeature()                
                


    def setupLayerConfig(self,override_int):
        '''Read internal OR external from main config file and set, default to internal'''
        #TODO... fix the ugly
        if override_int is None:
            if 'external' in map(lambda x: x.lower() if type(x) is str else x,self.mainconf.readDSParameters(self.DRIVER_NAME)):
                self.clearConfInternal()
            else:
                self.setConfInternal()
        else:
            self.setConfInternal() if override_int else self.clearConfInternal()
            

    def versionCheck(self):
        '''A version check to be used once the DS have been initialised... if normal checks cant be established eg psql on w32'''
        return True


class LayerInfo(object):
    '''Simple class for layer attributes'''
    def __init__(self,layer_id,layer_name=None,layer_defn=None,spatial_ref=None,geometry=None):
        #to clarify name confusion, id here refers to the layer 'name' read by the layer.GetName fuinction i.e v:xNNNN
        self.layer_id = layer_id
        #but name here refers to the descriptive name e.g. NZ Primary Parcels
        self.layer_name = layer_name
        self.layer_defn = layer_defn
        self.spatial_ref = spatial_ref
        self.geometry = geometry
        
        self.lce = None
        
    def setLCE(self,lce):
        self.lce = lce
        