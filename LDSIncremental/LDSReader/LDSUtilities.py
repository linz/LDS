'''
Simple LDS specific utilities class

Created on 28/08/2012

@author: jramsay
'''


import re
import os
import logging
import json

from StringIO import StringIO

from lxml import etree

ldslog = logging.getLogger('LDS')

class LDSUtilities(object):
    '''Does the LDS related stuff not specifically part of the datastore''' 

    
    @classmethod
    def splitLayerName(cls,layername):
        '''Splits a layer name typically in the format v:x### into /v/x### for URI inclusion'''
        return "/"+layername.split(":")[0]+"/"+layername.split(":")[1]
    
    @classmethod
    def cropChangeset(cls,layername):
        '''Removes changeset identifier from layer name'''
        return layername.rstrip("-changeset")
    
    @classmethod
    def checkDateFormat(cls,xdate):
        '''Checks a date parameter conforms to yyyy-MM-ddThh:mm:ss format'''        
        return type(xdate) is str and re.search('^\d{4}\-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?)$',xdate)

    # 772 time test string
    # http://wfs.data.linz.govt.nz/ldskey/v/x772-changeset/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=v:x772-changeset&viewparams=from:2012-09-29T07:00:00;to:2012-09-29T07:30:00&outputFormat=GML2
    
    @classmethod
    def checkLayerName(cls,lname):
        '''Makes sure a layer name conforms to v:x format'''
        return type(lname) is str and re.search('^v:x\d+$',lname) 
        
    @classmethod
    def checkCQL(cls,cql):
        '''Since CQL commands are freeform strings we need to try and validate at least the most basic errors. This is very simple
        RE matcher that just looks for valid predicates.
        
        <predicate> ::= <comparison predicate> | <text predicate> | <null predicate> | <temporal predicate> | <classification predicate> | <existence_predicate> | <between predicate> | <include exclude predicate>
               
        BNF http://docs.geotools.org/latest/userguide/library/cql/internal.html'''
        v = 0
        
        #comp pred
        if re.match('.*(?:!=|=|<|>|<=|>=)',cql):
            v+=1
        #text pred
        if re.match('.*(?:not\s*)?like.*',cql,re.IGNORECASE):
            v+=2
        #null pred
        if re.match('.*is\s*(?:not\s*)?null.*',cql,re.IGNORECASE):
            v+=4
        #time pred
        if re.match('.*(?:before|during|after)',cql,re.IGNORECASE):
            v+=8
        #clsf pred, not defined
        #exst pred
        if re.match('.*(?:does-not-)?exist',cql,re.IGNORECASE):
            v+=32
        #btwn pred
        if re.match('.*(?:not\s*)?between',cql,re.IGNORECASE):
            v+=64
        #incl pred
        if re.match('.*(?:include|exclude)',cql,re.IGNORECASE):
            v+=128
        #geo predicates just for good measure, returns v=16 overriding classification pred
        if re.match('.*(?:equals|disjoint|intersects|touches|crosses|within|contains|overlaps|bbox|dwithin|beyond|relate)',cql,re.IGNORECASE):
            v+=16
            
        ldslog.debug("CQL check:"+cql+":"+str(v))
        if v>0:
            return "&cql_filter="+cql
        else:
            return ""
        
    @classmethod    
    def precedence(cls,cmdline_arg,config_arg,layer_arg):
        '''Decide which CQL filter to apply based on scope and availability'''
        '''Currently we have; CommandLine > Config-File > Layer-Properties but maybe its better for individual layers to override a global setting... '''
        if cmdline_arg is not None and cmdline_arg != '':
            return cmdline_arg
        elif config_arg is not None and config_arg != '':
            return config_arg
        elif layer_arg is not None and layer_arg != '':
            return layer_arg
        return None
    
    @classmethod
    def extractFields(cls,feat):
        '''Extracts named fields from a layer config feature'''
        '''Not strictly independent but common and potentially used by a number of other classes'''
        try:
            pkey =  feat.GetField('PKEY')
        except:
            ldslog.debug("LayerSchema: No Primary Key Column defined, default to 'ID'")
            pkey = 'ID'
            
        '''names are/can-be stored so we can reverse search by layer name'''
        try:
            name = feat.GetField('NAME')
        except:
            ldslog.debug("LayerSchema: No Name saved in config for this layer, returning ID")
            name = None
            
        '''names are/can-be stored so we can reverse search by layer name'''
        try:
            group = feat.GetField('CATEGORY')
        except:
            ldslog.debug("Group List: No Groups defined for this layer")
            group = None
                  
        try:
            gcol = feat.GetField('GEOCOLUMN')
        except:
            ldslog.debug("LayerSchema: No Geo Column defined, default to 'SHAPE'")
            gcol = 'SHAPE'
            
        try:
            index = feat.GetField('INDEX')
        except:
            ldslog.debug("LayerSchema: No Index Column/Specification defined, default to None")
            index = None
            
        try:
            epsg = feat.GetField('EPSG')
        except:
            #print "No Projection Transformation defined"#don't really need to state the default occurance
            epsg = None
            
        try:
            lmod = feat.GetField('LASTMODIFIED')
        except:
            ldslog.debug("LayerSchema: No Last-Modified date recorded, successful update will write current time here")
            lmod = None
            
        try:
            disc = feat.GetField('DISCARD')
        except:
            disc = None 
            
        try:
            cql = feat.GetField('CQL')
        except:
            cql = None
            
        return (pkey,name,group,gcol,index,epsg,lmod,disc,cql)
    

class ConfigInitialiser(object):
    '''Initialises configuration, for use at first run'''

    @classmethod
    def buildConfiguration(cls,src,dst):
        '''Given a destination DS use this to select an XSL transform object and generate an output document that will initialise a new config file/table'''
        #df = os.path.normpath(os.path.join(os.path.dirname(__file__), "../debug.log"))
        
        uri = src.getCapabilities()
        xml = src.readDocument(uri)
        
        '''if we're going to the trouble of building a config initialiser then we're probably gonna want to run it'''
        if dst.config=='internal' and dst.CONFIG_XSL is not None:
            #converter = open(os.path.join(os.path.dirname(__file__), '../',dst.CONFIG_XSL),'r').read()
            converter = open(os.path.join(os.path.dirname(__file__), '../getcapabilities.json.xsl'),'r').read()
        else:
            converter = open(os.path.join(os.path.dirname(__file__), '../getcapabilities.file.xsl'),'r').read()

        
        xslt = etree.XML(converter)
        transform = etree.XSLT(xslt)
        
        doc = etree.parse(StringIO(xml))
        res = transform(doc)
        ldslog.debug(res)
        
        if dst.config=='internal':
            #execute the resulting SQL on the dst layer
            #dst.executeSQL(str(res))
            #decode the resulting JSON document and use it to build a new config layer 
            dst.buildConfigLayer(str(res))
        else:
            open(os.path.join(os.path.dirname(__file__), '../',dst.DRIVER_NAME.lower()+".layer.properties"),'w').write(str(res))
        

        
