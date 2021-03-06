<?xml version="1.0" encoding="ISO-8859-1"?>
<xsl:stylesheet version="1.0" 
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns="http://www.opengis.net/wfs" 
  xmlns:wfs="http://www.opengis.net/wfs"
  xmlns:ows="http://www.opengis.net/ows"
>

<!-- 
To make WFS2 work, change the namespace declarations to
xmlns:wfs="http://www.opengis.net/wfs/2.0" vs ~/wfs
xmlns:ows="http://www.opengis.net/ows/1.1" vs ~/ows
 -->
 
<xsl:output method="text" encoding="UTF-8"/>
<xsl:strip-space elements="*"/>

<xsl:template match="wfs:WFS_Capabilities">
	<xsl:apply-templates/>
</xsl:template>

<xsl:template match="wfs:FeatureTypeList">
	<xsl:text>[&#xa;</xsl:text>
	<xsl:for-each select="wfs:FeatureType">		
		<xsl:sort select="wfs:Name"/>
		<xsl:variable name="keyword" select="ows:Keywords/ows:Keyword"/>
		<xsl:variable name="title" select="wfs:Title"/>
		<!-- flags if layer kword is hydro or topo or the title contains zonemap -->
		<xsl:variable name="kflag">
			<xsl:if test="contains(normalize-space($title),'ZoneMap')">true</xsl:if>
		</xsl:variable>	

		<xsl:text>["</xsl:text><xsl:value-of select="normalize-space(wfs:Name)"/><xsl:text>",</xsl:text>
		<xsl:choose>
			<xsl:when test="normalize-space($kflag)='true'">
				<xsl:text>"id"</xsl:text>
			</xsl:when>
			<xsl:otherwise>
				<xsl:text>null</xsl:text>
			</xsl:otherwise>
		</xsl:choose>
		<xsl:text>,</xsl:text>
		<xsl:text>"</xsl:text><xsl:value-of select="normalize-space(wfs:Title)"/><xsl:text>",</xsl:text>
		<xsl:text>["</xsl:text>
		<xsl:for-each select="$keyword">
			<!-- <xsl:text>"</xsl:text> -->
			<xsl:value-of select="normalize-space(.)"/>
			<xsl:choose>
				<xsl:when test="position() != last()">
					<xsl:text>","</xsl:text>
				</xsl:when>
			</xsl:choose>
		</xsl:for-each>
        <xsl:text>"],</xsl:text>
		<xsl:text>null,</xsl:text>
		<xsl:choose>
			<xsl:when test="contains(wfs:Name,':table-')">
				<xsl:text>null,</xsl:text>
			</xsl:when>
			<xsl:otherwise>
				<xsl:text>"shape",</xsl:text>
			</xsl:otherwise>
		</xsl:choose>
		<xsl:text>null,</xsl:text>
		<xsl:text>null,</xsl:text>
		<xsl:text>null,</xsl:text>
		<xsl:choose>
			<xsl:when test="position() != last()">
				<xsl:text>null],&#xa;</xsl:text>
			</xsl:when>
			<xsl:otherwise>
				<xsl:text>null]&#xa;</xsl:text>
			</xsl:otherwise>
		</xsl:choose>
	</xsl:for-each>
	<xsl:text>]&#xa;</xsl:text>
</xsl:template>

<xsl:template match="*"/>
<!--
<xsl:template match="*">
    <xsl:message terminate="no">
        WARNING: Unmatched element: <xsl:value-of select="name()"/>
    </xsl:message>
</xsl:template>
-->

</xsl:stylesheet>
