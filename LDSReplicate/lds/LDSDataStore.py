'''
v.0.0.1

LDSReplicate -  LDSDataStore

Copyright 2011 Crown copyright (c)
Land Information New Zealand and the New Zealand Government.
All rights reserved

This program is released under the terms of the new BSD license. See the 
LICENSE file for more information.

LDSDataStore convenience subclass of WFSDataStore wrapping the LDS specific WFS instance. 

Created on 23/07/2012

@author: jramsay
'''
import re

import logging

from contextlib import closing
from lxml import etree
from lxml.etree import XMLSyntaxError

from lds.WFSDataStore import WFSDataStore
from urllib2 import urlopen, build_opener, install_opener, ProxyHandler
from lds.LDSUtilities import LDSUtilities
from lds.DataStore import MalformedConnectionString
from lds.VersionUtilities import AppVersion

ldslog = logging.getLogger('LDS')

class LDSDataStore(WFSDataStore):
    '''
    LDS DataStore provides standard options and URI methods along with convenience methods for common functions/documents expressed as 
    URI builders. For incremental specifically the change-column is defined here
    '''
    
    OGR_WFS_USE_STREAMING = 'NO'
    OGR_WFS_PAGE_SIZE = 10000
    OGR_WFS_PAGING_ALLOWED = 'OFF'
    
    OGR_WFS_LOAD_MULTIPLE_LAYER_DEFN = 'OFF'
    OGR_WFS_BASE_START_INDEX = 0
    
    GDAL_HTTP_USERAGENT = 'LDSReplicate/'+str(AppVersion.getVersion())    

    #Namespace declarations
    NS = {'g'    : '{http://data.linz.govt.nz/ns/g}', 
          'gml'  : '{http://www.opengis.net/gml}', 
          'xlink': '{http://www.w3.org/1999/xlink}', 
          'r'    : '{http://data.linz.govt.nz/ns/r}', 
          'ows'  : '{http://www.opengis.net/ows}', 
          'v'    : '{http://data.linz.govt.nz/ns/v}', 
          'wfs'  : '{http://www.opengis.net/wfs}', 
          'xsi'  : '{http://www.w3.org/2001/XMLSchema-instance}', 
          'ogc'  : '{http://www.opengis.net/ogc}'}

    def __init__(self,parent,conn_str=None,user_config=None):
        '''
        LDS init/constructor subclassing WFSDataStore
        '''
        #super WFS sets WFS driver and gets WFS config params
        #supersuper DataStore sets def flags (eg INCR)
        self.pkey = None
        self.psize = None
        self.pstart = None
        
        super(LDSDataStore,self).__init__(parent,conn_str,user_config)
        
        self.CHANGE_COL = "__change__"

        
        (self.url,self.key,self.svc,self.ver,self.fmt,self.cql) = self.params
        if self.conn_str:
            self.key = self.extractAPIKey(self.conn_str,False)
        
        #we're not going to try and overwrite LDS    
        self.clearOverwrite()

    def getConfigOptions(self):
        '''Adds GDAL options at driver initialisation, pagination_allowed and page_size'''
        #CPL_CURL_VERBOSE for those ogrerror/generalerror
        #OGR_WFS_PAGING_ALLOWED, OGR_WFS_PAGE_SIZE, OGR_WFS_BASE_START_INDEX
        local_opts  = ['GDAL_HTTP_USERAGENT='+str(self.GDAL_HTTP_USERAGENT)]
        local_opts += ['OGR_WFS_PAGING_ALLOWED='+str(self.OGR_WFS_PAGING_ALLOWED)]
        local_opts += ['OGR_WFS_PAGE_SIZE='+str(self.getPartitionSize() if self.getPartitionSize() else self.OGR_WFS_PAGE_SIZE)]
        local_opts += ['OGR_WFS_USE_STREAMING='+str(self.OGR_WFS_USE_STREAMING)]
        local_opts += ['OGR_WFS_LOAD_MULTIPLE_LAYER_DEFN='+str(self.OGR_WFS_LOAD_MULTIPLE_LAYER_DEFN)]
        local_opts += ['OGR_WFS_BASE_START_INDEX='+str(self.OGR_WFS_BASE_START_INDEX)]
        return super(LDSDataStore,self).getConfigOptions() + local_opts    
    
    def getLayerOptions(self,layer_id):
        '''Adds GDAL options at driver initialisation, pagination_allowed and page_size'''
        local_opts = []
        return super(LDSDataStore,self).getLayerOptions(layer_id) + local_opts
    
    def setPrimaryKey(self,pkey):
        '''Sets the name of the primary key column in the datasource object'''
        self.pkey = pkey
        
    def setPartitionSize(self,psize):
        '''Sets the partition size i.e. the number of features to be returned per WFS request'''
        self.psize = psize
        
    def getPartitionSize(self):
        return self.psize
        
    def setPartitionStart(self,pstart):
        '''Sets the starts point for LDS requests using the primary key as the index. Assumes the request will also be sorted by this same key'''
        self.pstart = pstart
        
    def getCapabilities(self):
        '''GetCapabilities endpoint constructor'''
        #validate the key by checking that the key can be extracted from the conn_str
        if not self.validateAPIKey(self.key):
            self.key = self.extractAPIKey(self.conn_str,True)
        #capabilities doc is fetched using urlopen, not wfs, so escaping isnt needed
        #uri = LDSUtilities.xmlEscape(self.url+self.key+"/wfs?service=WFS&version=1.1.0&request=GetCapabilities")
        uri = self.url+self.key+"/wfs?service=WFS&version=1.1.0&request=GetCapabilities"
        ldslog.debug(uri)
        return uri
    
    
    def validateAPIKey(self,kstr):
        '''Make sure the provided key conforms to the required format'''
        srch = re.search('[a-f0-9]{32}',kstr,flags=re.IGNORECASE)
        if srch is None:
            raise MalformedConnectionString('Cannot parse API key, '+str(kstr))
        return True
        
    def extractAPIKey(self,cs,raiseerr=False):
        '''if the user has supplied a connection string then they dont need to specify an API key in their config file, therefore we must extract it from the cs'''
        srch = re.search('/([a-f0-9]{32})/(v/x|wfs\?)',cs,flags=re.IGNORECASE)
        if srch is None and raiseerr:
            raise MalformedConnectionString('Cannot parse API key')
        return srch.group(1) if srch is not None else None
        
        
    def validateConnStr(self,cs):
        '''WFS basic checks. 1 url format,2 api key,3 ask for wfs'''
        if not re.search('^http://',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('\'http\' declaration required in LDS request')
        if not re.search('wfs\.data\.linz\.govt\.nz',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('Require \'wfs.data.linz.govt.nz\' in LDS address string')
        if not re.search('/[a-f0-9]{32}/(v/x|wfs\?)',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('Require API key (32char hex) in LDS address string')
        if not re.search('wfs\?',cs,flags=re.IGNORECASE):
            raise MalformedConnectionString('Need to specify \'wfs?\' service in LDS request')
        #look for conflicts
        ulayer = LDSUtilities.getLayerNameFromURL(cs)

        return cs,ulayer
        
    def buildIndex(self,lce,dst_layer_name):
        pass
        
    def sourceURI(self,layername,purpose=None):
        '''Basic Endpoint constructor'''
        if hasattr(self,'conn_str') and self.conn_str is not None:
            valid,urilayer = self.validateConnStr(self.conn_str)
            if layername is not None and urilayer!=layername:
                raise MalformedConnectionString('Layer specifications in URI differs from selected layer (-l); '+str(layername)+'!='+str(urilayer))
            return valid

        cql = self._buildCQLStr()
        #pql = self._buildPageStr()     
            
        typ = "##typeName="+layername
        ver = "##version="+self.ver if self.ver else ""
        svc = "##service="+self.svc if self.svc else "##service=WFS"
        req = "##request=GetFeature"
        #if omitted the outputformat parameter is null and default used, GML2
        fmt = "##outputFormat="+self.fmt if (self.fmt in self.SUPPORTED_OUTPUT_FORMATS) else ""
        uri = re.sub('##','&',re.sub('##','?',self.url+self.key+"/wfs"+svc+ver+req+typ+fmt+cql,1))
        ldslog.debug(uri)
        return uri

        
    def sourceURI_incrd(self,layername,fromdate,todate,purpose=None):
        '''Endpoint constructor fetching specific layers with incremental date fields'''
        if hasattr(self,'conn_str') and self.conn_str is not None:
            valid,urilayer = self.validateConnStr(self.conn_str)
            #I don't know why you would attempt to specify dates in the CL and in the URL as well but we might as well attempt to catch diffs
            if layername is not None and urilayer!=layername:
                raise MalformedConnectionString('Layer specifications in URI differs from selected layer (-l); '+str(layername)+'!='+str(urilayer))
            if (fromdate is not None and re.search('from:'+fromdate[:10],valid) is None) or (todate is not None and re.search('to:'+todate[:10],valid) is None):
                raise MalformedConnectionString("Date specifications in URI don't match those referred to with -t|-f "+str(todate)+'/'+str(fromdate)+" not in "+valid)
            return valid

        cql = self._buildCQLStr()
        #pql = self._buildPageStr()     
        
        vep = LDSUtilities.splitLayerName(layername)+"-changeset"
        typ = "##typeName="+layername+"-changeset"
        inc = "##viewparams=from:"+fromdate+";to:"+todate
        ver = "##version="+self.ver if self.ver else ""
        svc = "##service="+self.svc if self.svc else "##service=WFS"
        req = "##request=GetFeature"
        #if omitted the outputformat parameter is null and default used, GML2
        fmt = "##outputFormat="+self.fmt if (self.fmt in self.SUPPORTED_OUTPUT_FORMATS) else ""
        uri = re.sub('##','&',re.sub('##','?',self.url+self.key+vep+"/wfs"+svc+ver+req+typ+inc+fmt+cql,1))
        ldslog.debug(uri)
        return uri
    
    def sourceURI_feats(self,layername):
        '''Endpoint constructor to fetch number of features for a specific layer. for: Trigger manual paging for broken JSON'''
        #version must be 1.1.0 or > for this to work. NB outputFormat doesn't seem to have any effect here either so its omitted
        typ = "&typeName="+layername
        uri = self.url+self.key+"/wfs?service="+self.svc+"&version="+self.VERSION_COUNT+"&request=GetFeature&resultType=hits"+typ
        ldslog.debug(uri)
        return uri        
                    
    def rebuildDS(self):
        '''Resets the DS. Needed if the URI is edited'''
        self.setURI(LDSUtilities.reVersionURL(self.getURI(),LDSDataStore.VERSION_COUNT))
        self.read(self.getURI(),False)
    
    def _buildPageStr(self):
        '''Manual paging using startIndex instead of cql'''
        page = ""
        if self.psize is not None:
            page = "&startIndex="+str(self.pstart)+"&pagingallowed=On&sortBy="+self.pkey+"&maxFeatures="+str(self.psize)
            
        return page
    
    def _buildCQLStr(self):
        '''Builds a cql_filter string as set by the user appending an 'id>...' partitioning string if needed. NB. Manual partitioning is accomplished using the parameters, 'maxFeatures' to set feature quantity, a page-by-page recorded 'id' value and a 'sortBy=id' argument'''
        cql = ()
        maxfeat = ""
        
        #if implementing pagination in cql      
        if self.pstart is not None and self.psize is not None:
            cql += (self.pkey+">"+str(self.pstart),)
            #sortBy used so last feature will have the new maximum key, saves a comparison
            maxfeat = "&sortBy="+self.pkey+"&maxFeatures="+str(self.psize)            

        if self.getFilter() is not None:
            cql += (LDSUtilities.checkCQL(self.getFilter()),)

        return maxfeat+"&cql_filter="+';'.join(cql) if len(cql)>0 else ""    
    
    @classmethod
    def fetchLayerInfo(cls,url,proxy=None):
        '''Non-GDAL static method for fetching LDS layer ID's using etree parser.'''
        res = []
        content = None
        ftxp = "//{0}FeatureType".format(cls.NS['wfs'])
        nmxp = "./{0}Name".format(cls.NS['wfs'])
        ttxp = "./{0}Title".format(cls.NS['wfs'])
        kyxp = "./{0}Keywords/{0}Keyword".format(cls.NS['ows'])
        
        try:            
            if not LDSUtilities.mightAsWellBeNone(proxy): install_opener(build_opener(ProxyHandler(proxy)))
            #content = urlopen(url)#bug in lxml doesnt close url/files using parse method
            with closing(urlopen(url)) as content:
                tree = etree.parse(content)
                for ft in tree.findall(ftxp):
                    name = ft.find(nmxp).text
                    title = ft.find(ttxp).text
                    #keys = map(lambda x: x.text, ft.findall(kyxp))
                    keys = [x.text for x in ft.findall(kyxp)]
                    
                    res += ((name,title,keys),)
                
        except XMLSyntaxError as xe:
            ldslog.error('Error parsing URL;'+str(url)+' ERR;'+str(xe))
            
        return res

    
    def versionCheck(self):
        '''Nothing to check?'''
        #TODO maybe check gdal/wfs/gml etc
        return super(LDSDataStore,self).versioncheck()
        

        
        