'''
v.0.0.9

LDSReplicate -  MSSQLSpatialDataStore

Copyright 2011 Crown copyright (c)
Land Information New Zealand and the New Zealand Government.
All rights reserved

This program is released under the terms of the new BSD license. See the 
LICENSE file for more information.

Created on 9/08/2012

@author: jramsay
'''
import logging
import ogr
import re

from lds.DataStore import DataStore, MalformedConnectionString
from lds.LDSUtilities import LDSUtilities as LU, Encrypt

ldslog = LU.setupLogging()

class MSSQLSpatialDataStore(DataStore):
    '''
    MS SQL DataStore
    MSSQL:server=.\MSSQLSERVER2008;database=dbname;trusted_connection=yes
    '''

    DRIVER_NAME = DataStore.DRIVER_NAMES['ms']#"MSSQLSpatial"
    
    #wkbNone removed
    ValidGeometryTypes = (ogr.wkbUnknown, ogr.wkbPoint, ogr.wkbLineString,
                      ogr.wkbPolygon, ogr.wkbMultiPoint, ogr.wkbMultiLineString, 
                      ogr.wkbMultiPolygon, ogr.wkbGeometryCollection, 
                      ogr.wkbLinearRing, ogr.wkbPoint25D, ogr.wkbLineString25D,
                      ogr.wkbPolygon25D, ogr.wkbMultiPoint25D, ogr.wkbMultiLineString25D, 
                      ogr.wkbMultiPolygon25D, ogr.wkbGeometryCollection25D)
    
    BBOX = {'XMIN':-180,'XMAX':180,'YMIN':-90,'YMAX':90}
      
    def __init__(self,conn_str=None,user_config=None):
        '''
        cons init driver
        '''
        
        super(MSSQLSpatialDataStore,self).__init__(conn_str,user_config)
        
        (self.odbc,self.server,self.dsn,self.trust,self.dbname,self.schema,self.usr,self.pwd,self.config,self.srs,self.cql) = self.params
        

        
#     def clone(self):
#         clone = MSSQLSpatialDataStore(self.parent,self.conn_str,None)
#         clone.name = str(self.name)+'C'
#         return clone
    
    def sourceURI(self,layer):
        '''URI method returns source file name'''
        return self._commonURI(layer)
    
    def destinationURI(self,layer):
        '''URI method returns destination file name'''
        return self._commonURI(layer)
        
    def validateConnStr(self,cs):
        '''The MSSQL connection string must be something like (minimum); MSSQL:server=.\MSSQLSERVER2008;database=dbname;trusted_connection=yes'''
        if not re.search('^MSSQL:',cs,flags=re.IGNORECASE):
            '''TODO. We could append a MSSQL here instead'''
            raise MalformedConnectionString('MSSQL declaration must begin with \'MSSQL:\'')
        if not re.search('server=\'*[a-zA-Z0-9_\-\\\\]+\'*',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('\'server\' parameter required in MSSQL config string')
        if not re.search('database=\'*\w+\'*',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('\'database\' parameter required in MSSQL config string')
        return cs

    @staticmethod
    def buildConnStr(server,dbname,schema,trust,usr,pwd):
        cs = "MSSQL:server={0};database={1};schema={2}".format(server,dbname,schema)
        if trust=='yes':
            return cs + ";trusted_connection={0}'".format(trust)
        return cs + ";UID={0};PWD={1}".format(usr,pwd)
    
    def _commonURI(self,layer):
        '''Refers to common connection instance for example in a DB where it doesn't matter whether your reading or writing'''
        if hasattr(self,'conn_str') and self.conn_str:
            return self.validateConnStr(self.conn_str)
        #return "MSSQL:server={};database={};trusted_connection={};".format(self.server, self.dbname, self.trust)
        if LU.assessNone(self.pwd):
            if self.pwd.startswith(Encrypt.ENC_PREFIX):
                pwd = ";PWD={}".format(Encrypt.unSecure(self.pwd))
            else:
                pwd = ";PWD={}".format(self.pwd)
        else:
            pwd = ""
            
        sstr = ";Schema={}".format(self.schema) if LU.assessNone(self.schema) else ""
        usr = ";UID={}".format(self.usr) if LU.assessNone(self.usr) else ""
        drv = ";Driver='{}'".format(self.odbc) if LU.assessNone(self.odbc) else ""
        tcn = ";trusted_connection={}".format(self.trust) if LU.assessNone(self.trust) else ""
        uri = "MSSQL:server={};database={}".format(self.server, self.dbname, self.odbc)+usr+pwd+drv+sstr+tcn
        ldslog.debug(uri)
        return uri
        #uid/pwd/t_c squotes removed

    def constructLayerName(self,ref_name):
        '''compose a layer name with a schema prefix if one exists (has been specified)'''
        return self.schema+"."+LU.sanitise(ref_name) if (hasattr(self,'schema') and self.schema and self.schema is not '') else LU.sanitise(ref_name)

        
    def deleteOptionalColumns(self,dst_layer):
        '''Delete unwanted columns from layer, MSSQL version doesn't decrement index on column delete'''
        #might be better to do a "for col in optcols; delete col" assuming sg like 'get col names' is possible
        #because column deletion behaviour is different for each driver (advancing index or not) split out and subclass
        dst_layer_defn = dst_layer.GetLayerDefn()
        #loop layer fields and discard the unwanted columns
        for fi in range(0,dst_layer_defn.GetFieldCount()):
            fdef = dst_layer_defn.GetFieldDefn(fi)
            fdef_nm = fdef.GetName()
            #print '>>>>>',fi,fi-offset,fdef_nm
            if fdef and fdef_nm in self.optcols:
                self.deleteFieldFromLayer(dst_layer, fi,fdef_nm)
                
    def deleteFieldFromLayer(self,layer,field_id,field_name):
        '''per DS delete field since some do not support this'''
        dsql = "alter table "+layer.GetName()+" drop column "+field_name
        self.executeSQL(dsql)
        #ldslog.error("Field deletion not supported in MSSQLSpatial driver")

    def buildIndex(self):
        '''Builds an index creation string for a new full replicate'''
        tableonly = self.dst_info.ascii_name.split('.')[-1]
        
        if LU.assessNone(self.dst_info.pkey):
            cmd = 'ALTER TABLE {0} ADD CONSTRAINT {1}_{2}_PK UNIQUE({2})'.format(self.dst_info.ascii_name,tableonly,self.dst_info.pkey)
            try:
                self.executeSQL(cmd)
                ldslog.info("Index = {}({}). Execute = {}".format(tableonly,self.dst_info.pkey,cmd))
            except RuntimeError as rte:
                if re.search('already exists', str(rte)): 
                    ldslog.warn(rte)
                else:
                    raise        
                
        if LU.assessNone(self.dst_info.geocolumn):
            cmd = 'CREATE SPATIAL INDEX {1}_{2}_GK ON {0}({2})'.format(self.dst_info.ascii_name,tableonly,self.dst_info.geocolumn)
            cmd += ' WITH (BOUNDING_BOX = (XMIN = {0},YMIN = {1},XMAX = {2},YMAX = {3}))'.format(self.BBOX['XMIN'],self.BBOX['YMIN'],self.BBOX['XMAX'],self.BBOX['YMAX'])
            #cmd = 'CREATE SPATIAL INDEX ON {}'.format(tableonly)
            try:
                self.executeSQL(cmd)
                ldslog.info("Index = {}({}). Execute = {}".format(tableonly,self.dst_info.geocolumn,cmd))
            except RuntimeError as rte:
                if re.search('already exists', str(rte)): 
                    ldslog.warn(rte)
                else:
                    raise
                

    def getConfigOptions(self):
        '''dataset creation not supported so no options'''
        local_opts = []
        return super(MSSQLSpatialDataStore,self).getConfigOptions() + local_opts
    
    def getLayerOptions(self,layer_id):
        '''Get MS options for GEO_NAME'''
        #GEOM_TYPE, OVERWRITE, LAUNDER, PRECISION, DIM={2,3}, GEOM_NAME, SCHEMA, SRID
        
        local_opts = ['MARS Connection=TRUE']
        gc = self.layerconf.readLayerProperty(layer_id,'geocolumn')
        if gc:
            local_opts += ['GEOM_NAME='+gc]
            
        schema = self.confwrap.readDSProperty(self.DRIVER_NAME,'schema')
        if schema is None:
            schema = self.schema
        if LU.assessNone(schema) and LU.containsOnlyAlphaNumeric(schema):
            local_opts += ['SCHEMA='+schema]
            
        srid = self.layerconf.readLayerProperty(layer_id,'epsg')
        if srid:
            local_opts += ['SRID='+srid]
        
        return super(MSSQLSpatialDataStore,self).getLayerOptions(layer_id) + local_opts
    
            
    def selectValidGeom(self,geom):
        '''Override for wkbNone'''
        return geom if geom in self.ValidGeometryTypes else ogr.wkbUnknown

    def changeColumnIntToString(self,table,column):
        '''MSSQL column type changer. Used to change 64 bit integer columns to string. NB Default varchar length for MS is 1!. so, 2^64 ~ 10^19 allow 32 chars''' 
        '''No longer used!'''
        self.executeSQL('alter table '+table+' alter column '+column+' varchar(32)')
    
    def _clean(self):
        '''Deletes the entire DS layer by layer'''
        #for MSSQL deleted indices don't decrement
        for li in range(0,self.ds.GetLayerCount()):
            if self._cleanLayerByIndex(self.ds,li):
                self.clearLastModified(li)
                
    def versionCheck(self):
        '''MSSQL version checker'''
        #Microsoft SQL Server 2008 R2 (RTM) - 10.50.1600.1
        #Microsoft SQL Server 2008 (SP3) - 10.0.5500.0 (X64)   Sep 21 2011 22:45:45   Copyright (c) 1988-2008 Microsoft Corporation  Standard Edition (64-bit) on Windows NT 5.2 <X64> (Build 3790: Service Pack 2) (VM) 
        from VersionUtilities import VersionChecker,UnsupportedVersionException

        msv_cmd = 'SELECT @@version'

        msv_res = re.search('Microsoft SQL Server.+- (\d+\.\d+\.\d+\.*\d*)',self.executeSQL(msv_cmd).GetNextFeature().GetFieldAsString(0))
        
        if VersionChecker.compareVersions(VersionChecker.MSSQL_MIN, msv_res.group(1) if msv_res else VersionChecker.MSSQL_MIN):
            raise UnsupportedVersionException('MSSQL version '+str(msv_res.group(1))+' does not meet required minumum '+str(VersionChecker.MSSQL_MIN))
        
        ldslog.info(self.DRIVER_NAME+' version '+str(msv_res.group(1)))
        return True
    