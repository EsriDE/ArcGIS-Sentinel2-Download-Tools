# -*- coding: UTF-8 -*-

# Copyright 2017 Esri Deutschland Group GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# TODO: Tons of!!!
VERSION=20170302
import arcpy,os,sys
HERE=os.path.dirname(__file__); sys.path.append(os.path.join(HERE,"lib"))
try: reload(sensub) # With this, changes to the module's .py file become effective on a toolbox Refresh (F5) from within ArcGIS, i.e. without having to restart ArcGIS.
except NameError: import sensub
sensub.arcpy, sensub.THERE = arcpy, HERE
ARCMAP = arcpy.sys.executable.endswith("ArcMap.exe")
DHUSUSR = arcpy.Parameter("DHUSUSR", "DHuS user name", datatype="GPString")
DHUSPWD = arcpy.Parameter("DHUSPWD", "DHuS password", datatype="GPStringHidden")
DHUSALT = arcpy.Parameter("DHUSALT", "DHuS alternative site", datatype="GPString", parameterType="Optional")
DHUSALT.filter.type="ValueList"; DHUSALT.filter.list=["CODE-DE"]

class Toolbox (object):
  def __init__ (self):
    """Initialize the toolbox (toolbox name is the name of the .pyt file)."""
    self.label = "Sentinel"
    self.tools = [Search,Download] # Keep in sync with toolbox tool class names (see below)!
    self.alias = ""

class Search (object):
  """WHERE does this python docstring appear? In ArcCatalog? Elsewhere??"""
  i=dict() # Map parameter name to parameter index; provides 'parameter by name'.
  w=dict() # Forward warning messages from updateParameters to updateMessages. (Is there a better way doing this?)
  WGS84 = arcpy.SpatialReference("WGS 1984")
  CME = "CopiedMapExtent"

  def __init__ (self):
    """Initialize the tool (tool name is the name of the class)."""
    self.label = "Search DHuS catalog" # Displayed name.
    self.description = "Search Data Hub Services' (DHuS) product catalog for Sentinel-2 L1C products according to given criteria (in particular spatiotemporal constraints and cloud cover limit)."
    self.canRunInBackground = False
    if ARCMAP: # Dispose well-known broken in_memory layers:
      try:
        mxd=arcpy.mapping.MapDocument("CURRENT")
        for df in arcpy.mapping.ListDataFrames(mxd):
          for lyr in arcpy.mapping.ListLayers(mxd, self.CME+"*", df):
            if lyr.isBroken: arcpy.mapping.RemoveLayer(df, lyr)
      except RuntimeError: pass # "Object: CreateObject cannot open map document"! This happens after having edited the "Item Description..." (enforces to restart ArcGIS)!

  def getParameterInfo (self): # Why arcpy always calls getParameterInfo multiple times (up to seven times when a tool is called using arcpy.ImportToolbox("P:/ath/to/File.pyt"))?? Instantiation of each toolbox tool class happens even oftener.
    """Prepare parameter definitions."""
    params=[DHUSUSR,DHUSPWD,DHUSALT]
    SENSINGMIN = arcpy.Parameter("SENSINGMIN", "Sensing earliest date", datatype="GPDate"); params.append(SENSINGMIN)
    params.append(arcpy.Parameter("SENSINGMAX", "Sensing latest date", datatype="GPDate", parameterType="Optional"))
    AOIENV = arcpy.Parameter("AOIENV", "Area Of Interest (AOI) Envelope in decimal degrees", datatype="GPEnvelope"); params.append(AOIENV)
    aoiMap = arcpy.Parameter("aoiMap", "Use current map extent for AOI Envelope", datatype="GPBoolean", parameterType="Optional"); params.append(aoiMap)
    if not ARCMAP: aoiMap.enabled=False
    params.append(arcpy.Parameter("aoiLayer", "Use layer extent for AOI Envelope", datatype="GPLayer", parameterType="Optional"))
#    OVERLAPMIN = arcpy.Parameter("OVERLAPMIN", "Minimum AOI overlap percentage", datatype="GPLong", parameterType="Optional")
#    OVERLAPMIN.filter.type="Range"; OVERLAPMIN.filter.list=[1,100]; params.append(OVERLAPMIN)
    CLOUDYMAX = arcpy.Parameter("CLOUDYMAX", "Maximum cloud cover percentage", datatype="GPLong", parameterType="Optional")
    CLOUDYMAX.filter.type="Range"; CLOUDYMAX.filter.list=[0,100]; params.append(CLOUDYMAX)
    FGDB = arcpy.Parameter("FGDB", "File geodatabase holding the search results catalog", datatype="DEWorkspace")
    FGDB.filter.list=["Local Database"]; params.append(FGDB)
    CATNAME = arcpy.Parameter("CATNAME", "Name of the local search results catalog", datatype="GPString"); params.append(CATNAME)
    OPMERGE = arcpy.Parameter("OPMERGE", "Merge new finds with ones from previous searches.", datatype="GPBoolean", parameterType="Optional"); params.append(OPMERGE)
    ROWSMAX = arcpy.Parameter("ROWSMAX", "Maximum count of search result rows", datatype="GPLong", parameterType="Optional")
    ROWSMAX.filter.type="Range"; ROWSMAX.filter.list=[1,5000]; params.append(ROWSMAX)
    params.append(arcpy.Parameter("PRODCAT", parameterType="Derived", datatype="DERasterCatalog", symbology=sensub.dep("Product.lyr"), direction="Output")) # Why direction must/can be specified when "Derived" implicitly enforces "Output"??
#    params.append(arcpy.Parameter("aoiTmp", parameterType="Derived", datatype="DEFeatureClass", symbology=sensub.dep(self.CME+".lyr"), direction="Output"))
#    params.append(arcpy.Parameter("debug", "debug", datatype="GPString", parameterType="Optional"))
    # Preset:
    sensub.recall(self, params, ["aoiMap","aoiLayer"])
    if SENSINGMIN.value is None: SENSINGMIN.value = sensub.dayStart(datetime.date.today() - datetime.timedelta(days=30))
    if AOIENV.value is None: AOIENV.value = sensub.AOIDEMO
    aoiMap.value=False # Paranoid.
#    if OVERLAPMIN.value is None: OVERLAPMIN.value=1
    if CLOUDYMAX.value is None: CLOUDYMAX.value=50
    if CATNAME.value is None: CATNAME.value="Product"
    if OPMERGE.value is None: OPMERGE.value=True
    if ROWSMAX.value is None: ROWSMAX.value=25
    return params


  def updateParameters (self, params):
    """Modify the values and properties of parameters before internal validation is performed. This method is called whenever a parameter has been changed."""
    AOIENV,aoiLayer,aoiMap = params[self.i["AOIENV"]], params[self.i["aoiLayer"]], params[self.i["aoiMap"]]
    if not AOIENV.hasBeenValidated:
      aoiLayer.enabled = AOIENV.enabled = True # Why GPEnvelope's widget allows "Clear" when not being enabled??
      if ARCMAP: aoiMap.enabled=True
      aoiMap.value = False
    elif not aoiMap.hasBeenValidated:
      if aoiMap.value and ARCMAP:
        mxd=arcpy.mapping.MapDocument("CURRENT")
        e = mxd.activeDataFrame.extent
        pe = sensub.prjExtent(self, e, "aoiMap", "Active data frame")
        if pe:
          params[self.i["AOIENV"]].value = pe
          tmpName = "%s%d" % (self.CME, arcpy.mapping.ListDataFrames(mxd).index(mxd.activeDataFrame))
          tmpSource = os.path.join("in_memory",tmpName)
          fresh=False
          if not arcpy.Exists(tmpSource):
            arcpy.CreateFeatureclass_management("in_memory", tmpName, "POLYGON", spatial_reference=self.WGS84)
            fresh=True
          ll = arcpy.mapping.ListLayers(mxd, tmpName, mxd.activeDataFrame)
          if not ll: arcpy.mapping.AddLayer(mxd.activeDataFrame, arcpy.mapping.Layer(tmpSource))
          if fresh or not ll: arcpy.ApplySymbologyFromLayer_management(tmpName, sensub.dep(self.CME+".lyr"))
          if not fresh: # Dispose previous CME beforehand:
            with arcpy.da.UpdateCursor(tmpSource,"OID@") as rows:
              for row in rows: rows.deleteRow()
          with arcpy.da.InsertCursor(tmpSource,"SHAPE@") as rows: rows.insertRow([e.polygon])
          if not fresh: arcpy.RefreshActiveView()
          AOIENV.enabled = aoiLayer.enabled = False
        else: aoiMap.value=False
      else: AOIENV.enabled = aoiLayer.enabled = True
    elif not aoiLayer.hasBeenValidated:
      if aoiLayer.value:
        dismiss=False
        if not aoiLayer.valueAsText.endswith(".lyr") and ARCMAP:
          mxd=arcpy.mapping.MapDocument("CURRENT")
          dfLayers = (lyr.name for lyr in arcpy.mapping.ListLayers(mxd, data_frame=mxd.activeDataFrame))
          if aoiLayer.valueAsText not in dfLayers:
            self.w["aoiLayer"]="Layer not found in active data frame, nothing copied over."
            dismiss=True
        if not dismiss:
          if hasattr(aoiLayer.value,"dataSource") and aoiLayer.value.dataSource: # "Basemap" has no dataSource attribute! And 'geoprocessing Layer object' has no supports() funtion.
            d = arcpy.Describe(aoiLayer.value.dataSource)
            if d.dataType=="FeatureDataset": self.w["aoiLayer"]="FeatureDataset found, nothing copied over."
            else:
              pe = sensub.prjExtent(self, d.extent, "aoiLayer", "Data source")
              if pe: params[self.i["AOIENV"]].value = pe
          else: self.w["aoiLayer"]="Data source info not found, nothing copied over."
#        else: aoiLayer.value="" # Silently dismiss.
        AOIENV.enabled = aoiMap.enabled = False
      else: # Release other:
        AOIENV.enabled=True
        if ARCMAP: aoiMap.enabled=True

    CATNAME = params[self.i["CATNAME"]]
    if not CATNAME.hasBeenValidated: CATNAME.value = arcpy.ValidateTableName(CATNAME.value, params[self.i["FGDB"]].value)


  def updateMessages (self, params):
    """Modify the messages created by internal validation for each tool parameter. This method is called after internal validation."""
    for k in self.w.keys(): params[self.i[k]].setWarningMessage(self.w.pop(k))

    SENSINGMIN,SENSINGMAX = params[self.i["SENSINGMIN"]], params[self.i["SENSINGMAX"]]
    if SENSINGMIN.value:
      sensub.enforceDateOnly(SENSINGMIN)
      S2first,present = datetime.date(2015,6,28), datetime.date.today()
      if SENSINGMIN.value.date()<S2first:
        SENSINGMIN.setWarningMessage("Earliest image from Sentinel-2 is dated "+S2first.isoformat())
        SENSINGMIN.value = sensub.dayStart(S2first)
      elif SENSINGMIN.value.date()>present:
        SENSINGMIN.setWarningMessage("Sensing earliest date cannot lie in the future.")
        SENSINGMIN.value = sensub.dayStart(present)
    sensub.enforceDateOnly(SENSINGMAX)
    if SENSINGMIN.value and SENSINGMAX.value and SENSINGMIN.value.date()>=SENSINGMAX.value.date():
      SENSINGMAX.setWarningMessage("Sensing latest date must not be before or equal to Sensing earliest date.")
      SENSINGMAX.value = SENSINGMIN.value + datetime.timedelta(days=1)

    AOIENV = params[self.i["AOIENV"]]
    if AOIENV.value:
      e = AOIENV.value
      if (e.XMax-e.XMin)>10 or (e.YMax-e.YMin)>10: AOIENV.setErrorMessage("Must be within an area described by 10° of longitude and 10° of latitude.") # DHuS OpenSearch limitation.

#    aoiLayer = params[self.i["aoiLayer"]]
#    if aoiLayer.hasWarning() or aoiLayer.hasError(): # Release all:
#      aoiLayer.enabled = AOIENV.enabled = True
#      if ARCMAP: params[self.i["aoiMap"]].enabled=True

    FGDB = params[self.i["FGDB"]]
    if FGDB.valueAsText and FGDB.valueAsText.endswith(".lyr"): FGDB.setErrorMessage("Not a workspace.") # Why DEWorkspace validates a .lyr file as a Workspace??
    OPMERGE = params[self.i["OPMERGE"]]
    if not OPMERGE.value: OPMERGE.setWarningMessage("Without Merge, existing finds from previous searches will be deleted from the local search results catalog.")


  def execute (self, params, messages):
    """Apply the tool."""
    sensub.memorize(params)
    FGDB,CATNAME = params[self.i["FGDB"]], params[self.i["CATNAME"]]
    prodCat,fresh = os.path.join(FGDB.valueAsText,CATNAME.valueAsText), False
    os.environ["PRODCAT"]=prodCat # Preset for Download tool.

    e = params[self.i["AOIENV"]].value; aoiEnv = "%f %f %f %f" % (e.XMin,e.YMin,e.XMax,e.YMax)
    sensub.auth(params[self.i["DHUSUSR"]].value, params[self.i["DHUSPWD"]].value, params[self.i["DHUSALT"]].value)
    finds = sensub.search(params[self.i["SENSINGMIN"]].value, params[self.i["SENSINGMAX"]].value, aoiEnv, 1, params[self.i["CLOUDYMAX"]].value, params[self.i["ROWSMAX"]].value) # OVERLAPMIN currently not implemented, set to a fixed dummy value.
    if not finds: return

    if not arcpy.Exists(prodCat):
      arcpy.AddWarning(prodCat+": does not yet exist, creating on the fly...")
      SRS = arcpy.SpatialReference("WGS 1984 Web Mercator (Auxiliary Sphere)")
      arcpy.CreateRasterCatalog_management(FGDB.value, CATNAME.value, SRS, SRS, raster_management_type="MANAGED")
      arcpy.AddField_management(prodCat,"SensingDate","DATE")
      arcpy.AddField_management(prodCat,"CloudCover","FLOAT")
      arcpy.AddField_management(prodCat,"Size","TEXT",field_length=12)
      arcpy.AddField_management(prodCat,"Added","DATE")
      arcpy.AddField_management(prodCat,"Marked","SHORT")
      arcpy.AddField_management(prodCat,"Downloaded","DATE")
      arcpy.AddField_management(prodCat,"Found","DATE")
      arcpy.AddField_management(prodCat,"Title","TEXT",field_length=80)
      arcpy.AddField_management(prodCat,"UUID","TEXT",field_length=36)
      arcpy.AddField_management(prodCat,"MD5","TEXT",field_length=32)
      for fieldName in "UUID","Name","Title","SensingDate","CloudCover","Size","Added","Marked","Downloaded","Found","MD5": arcpy.AddIndex_management(prodCat,fieldName,fieldName)
      fresh=True
    truncated=False
    if not fresh and not params[self.i["OPMERGE"]].value:
      arcpy.AddWarning("Merge option not chosen, therefore deleting all existing finds (that originate from previous searches).")
      arcpy.TruncateTable_management(prodCat); truncated=True

    allFinds,exclusion = set(finds.iterkeys()), set()
    if not truncated: # Exclude already existent products from re-fetching their previews:
      existent=set()
      with arcpy.da.SearchCursor(prodCat, "UUID", where_clause="UUID IN "+sensub.sql(allFinds), sql_clause=("DISTINCT",None)) as rows:
        for r in rows: existent.add(r[0])
      exclusion = allFinds.intersection(existent)
    newFinds = allFinds.difference(exclusion)
    newCount,exclusionCount = len(newFinds), len(exclusion)
    arcpy.AddMessage("New finds: %d, already existent in local catalog: %d" % (newCount, exclusionCount))

    if newCount>0:
      arcpy.AddMessage("Fetching metadata, tile preview(s) for...")
      tmpDir = os.path.join(os.path.realpath(os.environ["TEMP"]), "previews") + datetime.datetime.now().strftime("%Y%m%d%H%M%S") # What about module "tempfile"?
      os.mkdir(tmpDir); toRemove=set()
      for p,UUID in enumerate(newFinds,1):
        Title,SensingDate,CloudCover,Size = finds[UUID]
        arcpy.AddMessage("...new find %d/%d (%s)," % (p,newCount, SensingDate))
        tiles,urlFormat = sensub.prodTiles(Title,UUID,SensingDate)
        tileCount = len(tiles)
        for t,(tileName,previewPath) in enumerate(tiles.items(),1):
          arcpy.AddMessage("  tile %d/%d (%s)" % (t,tileCount,tileName))
          target,issue,severity = sensub.download(urlFormat%previewPath, tmpDir, "%s.%s.jp2"%(UUID,tileName), slim=True)
          if not issue or issue=="already exists":
            toRemove.add(target); auxPath=target+".aux.xml"
            if not os.path.exists(auxPath):
              with open(auxPath,"w") as aux: aux.write("<PAMDataset><PAMRasterBand band='1'><NoDataValue>0</NoDataValue></PAMRasterBand><PAMRasterBand band='2'><NoDataValue>0</NoDataValue></PAMRasterBand><PAMRasterBand band='3'><NoDataValue>0</NoDataValue></PAMRasterBand></PAMDataset>")
              toRemove.add(auxPath)
      arcpy.AddMessage("Appending new tile preview(s)...")
      arcpy.env.rasterStatistics = "NONE" # I.e. no persisted histogram stretching. Alternatively, choose "STATISTICS 1 1 (0 255)".
      arcpy.WorkspaceToRasterCatalog_management(tmpDir, prodCat)
      for f in toRemove: os.remove(f)
      os.rmdir(tmpDir)

    arcpy.AddMessage("Updating attributes...")
    when = datetime.datetime.now()
    wcl = "UUID IS NULL"
    if exclusionCount>0: wcl += " OR UUID IN "+sensub.sql(exclusion)
    with arcpy.da.UpdateCursor(prodCat, ("UUID","Name","Title","SensingDate","CloudCover","Size","Added","Marked","Found"), where_clause=wcl) as rows:
      for r in rows:
        if r[0]: r[8]=when # Found again.
        else: # New find:
          UUID,tileName,sfx = r[1].split(".")
          if finds.has_key(UUID): # Paranoid... maybe there are some relicts from a previous unhandled cancellation/crash?
            Title,SensingDate,CloudCover,Size = finds[UUID]
            r = [UUID, "%s %s"%(tileName,SensingDate.date().isoformat()), Title,SensingDate,CloudCover,Size,when,None,when]
        rows.updateRow(r)
    if ARCMAP: params[self.i["PRODCAT"]].value = prodCat
    #HOWTO "Reload Cache" from arcpy? Is comtypes needed for this?



class Download (object):
  i=dict() # Map parameter name to parameter index; provides 'parameter by name'.
  import collections
  modes = collections.OrderedDict([
    ("CartOnly", "Cart-only (no raster data)"),
    ("Full", "Full product (cart in parallel)"),
    ("ImgSel", "Image selection (bare raster)")]) # Provide displayName (label) by mode name.
  images = collections.OrderedDict([
    ("B01","Coastal aerosol, 443nm(20nm), 60m"),
    ("B02","Blue, 490nm(65nm), 10m"),
    ("B03","Green, 560nm(35nm), 10m"),
    ("B04","Red, 665nm(30nm), 10m"),
    ("B05","Vegetation (red edge), 705nm(15nm), 20m"),
    ("B06","Vegetation (red edge), 740nm(15nm), 20m"),
    ("B07","Vegetation (red edge), 783nm(20nm), 20m"),
    ("B08","NIR (broad), 842nm(115nm), 10m"),
    ("B8A","Vegetation (red edge), 865nm(20nm), 20m"),
    ("B09","Water vapour, 945nm(20nm), 60m"),
    ("B10","SWIR (cirrus), 1380nm(30nm), 60m"),
    ("B11","SWIR (snow/ice/cloud), 1610nm(90nm), 20m"),
    ("B12","SWIR (snow/ice/cloud), 2190nm(180nm), 20m"),
    ("TCI","Natural color composite (3•8 bit), 10m")])
  imgNames = images.keys()

  def __init__ (self):
    self.label = "Download Marked packages" # Displayed name.
    self.description = "For each Marked entry in the local product catalog, download the respective raster data package."
    self.canRunInBackground = False

  def getParameterInfo (self):
    params=[DHUSUSR,DHUSPWD,DHUSALT]
    params.append(arcpy.Parameter("PRODCAT", "Product catalog where Marked rows denote download", datatype="DERasterCatalog"))
    params.append(arcpy.Parameter("RASTERDIR", "Directory to store downloads", datatype="DEFolder"))
    OPMODE = arcpy.Parameter("OPMODE", "Operation mode", datatype="GPString", parameterType="Optional")
    OPMODE.filter.type="ValueList"; OPMODE.filter.list=self.modes.values(); params.append(OPMODE)
    UNZIP = arcpy.Parameter("UNZIP", "Unzip .zip after download", datatype="GPBoolean", parameterType="Optional"); params.append(UNZIP)
    for n,dn in self.images.iteritems():
      params.append(arcpy.Parameter(n, "%s: %s"%(n,dn), category="Image selection", datatype="GPBoolean", parameterType="Optional"))
    params.append(arcpy.Parameter("DEMO", parameterType="Derived", datatype="DERasterDataset", multiValue=True, symbology=sensub.dep("Multispectral-10m.lyr"), direction="Output")) # Just for demonstration purposes of this built-in function template.
    params.append(arcpy.Parameter("RGB8", parameterType="Derived", datatype="DERasterDataset", multiValue=True, symbology=sensub.dep("TCI.lyr"), direction="Output")) # New image option (beginning with PSD14).
    # Preset:
    sensub.recall(self,params)
    if OPMODE.value is None: OPMODE.value=self.modes["CartOnly"]
    if UNZIP.value is None: UNZIP.value=True
    for n in ["TCI"]: #"B04","B03","B02"
      I = params[self.i[n]]
      if I.value is None: I.value=True
    return params

  def updateParameters (self, params):
    OPMODE,UNZIP = params[self.i["OPMODE"]], params[self.i["UNZIP"]]
    if not OPMODE.hasBeenValidated:
      if OPMODE.value==self.modes["Full"]: UNZIP.enabled=True
      else: UNZIP.enabled=False
      if OPMODE.value==self.modes["ImgSel"]: available=True
      else: available=False
      for n in self.imgNames: params[self.i[n]].enabled=available

  def updateMessages (self, params):
    RASTERDIR = params[self.i["RASTERDIR"]]
    if RASTERDIR.value:
      rp,MAXLEN = os.path.realpath(RASTERDIR.valueAsText), 11
      if len(rp)>MAXLEN: RASTERDIR.setErrorMessage("%s: Path too long (max. %d characters, incl. drive letter and dir. sep.)." % (rp,MAXLEN))

    OPMODE = params[self.i["OPMODE"]]
    if OPMODE.value==self.modes["ImgSel"]:
      anySelected=False
      for n in self.imgNames:
        if params[self.i[n]].value: anySelected=True
      if not anySelected: OPMODE.setErrorMessage("Image selection is empty (see below), please select at least one image.")


  def execute (self, params, messages):
    sensub.memorize(params)
    prodCat = params[self.i["PRODCAT"]].valueAsText
    catName = os.path.basename(prodCat)
    os.environ["CATNAME"]=catName; os.environ["FGDB"]=os.path.dirname(prodCat) # Preset for Search tool.
    rasterDir = os.path.realpath(params[self.i["RASTERDIR"]].valueAsText)
    m,opMode = params[self.i["OPMODE"]].value, dict()
    for n in self.modes.keys(): opMode[n] = True if m==self.modes[n] else False
    unzip,demo,rgb8 = params[self.i["UNZIP"]].value, list(), list()
#    cursor = arcpy.da.SearchCursor if opMode["CartOnly"] else arcpy.da.UpdateCursor
    with arcpy.da.UpdateCursor(prodCat, ["Name","SensingDate","Size","Marked","Downloaded","Title","UUID","MD5"], where_clause="UUID IN (SELECT DISTINCT UUID FROM "+catName+" WHERE Marked>0)", sql_clause=(None,"ORDER BY Marked DESC")) as rows:
      if not sensub.hasNext(rows):
        arcpy.AddWarning("Nothing Marked for download!")
        return
      arcpy.AddMessage("Processing Marked item(s)...")
      prodMemo = dict()
      if not opMode["ImgSel"]:
        dldone = dlskipped = dlfailed = missed = 0
        cartName = os.path.join(rasterDir, datetime.datetime.now().strftime("Cart.%Y-%m-%d_%H.%M.%S.xml"))
        cartPart = cartName+sensub.PARTIAL
        cartFile = open(cartPart,"w")
        sensub.flushline('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<metalink xmlns="urn:ietf:params:xml:ns:metalink">', cartFile)
      sensub.auth(params[self.i["DHUSUSR"]].value, params[self.i["DHUSPWD"]].value, params[self.i["DHUSALT"]].value)
      for r in rows:
        update = False
        Name,SensingDate,Size,Marked,Downloaded,Title,UUID,MD5 = r
        if not opMode["ImgSel"]:
          processed,md5sum,issue,severity = (None,MD5,None,0) if not prodMemo.has_key(UUID) else prodMemo.get(UUID)
          if not processed: # Yet unprocessed single-tile package, or first tile occurrence of a multi-tile package (scene) or of a dupes set (should not happen):
            arcpy.AddMessage("# %s, %s (%s)" % (Size, Title, UUID))
            if not md5sum: md5sum,issue,severity = sensub.md5sum(UUID)
            if not md5sum:
              arcpy.AddWarning(" => Missed."); missed += 1
            else:
              m4int = (filename,md5sum,url) = Title+".zip", md5sum, sensub.SITE["SAFEZIP"]%UUID
              sensub.flushline("  <file name='%s'><hash type='MD5'>%s</hash><url>%s</url></file>" % m4int, cartFile)
              if opMode["Full"]:
                target,issue,severity = sensub.download(url, rasterDir, filename, md5sum, unzip, Title+".SAFE")
                if not issue:
                  dldone += 1
                  if unzip:
                    if len(Title)<sensub.PSD13LEN: rgb8.append(target) # PSD14 not yet supported by ArcGIS(10.5).
                    else: demo.append(os.path.join(target,"Multispectral-10m"))
                elif severity==1:
                  arcpy.AddWarning(" => Skipped."); dlskipped += 1
                else: dlfailed += 1
            processed = datetime.datetime.now()
          if not MD5 and md5sum:
            r[7]=md5sum; update=True # Cache it to avoid potentially redundant checksum calls.
          if opMode["Full"] and not issue:
            r[4]=processed; update=True
          prodMemo[UUID] = (processed,md5sum,issue,severity)
        elif Marked:
          tileName = Name.split()[0]
          arcpy.AddMessage("# %s, %s," % (Title,tileName))
          if not prodMemo.has_key(UUID): prodMemo[UUID] = sensub.prodTiles(Title,UUID,SensingDate,False)
          tiles,urlFormat = prodMemo.get(UUID)
          tileDir = os.path.join(rasterDir, Title, tileName)
          if not os.path.exists(tileDir): os.makedirs(tileDir)
          anyImageDownloaded=False
          for n in self.imgNames:
            if params[self.i[n]].value:
              if n=="TCI" and not len(Title)<sensub.PSD13LEN: arcpy.AddWarning("  TCI: not available for older products (PSD<14).")
              else:
                arcpy.AddMessage("  %s," % n)
                target,issue,severity = sensub.download(urlFormat % (tiles[tileName] % n), tileDir, n+".jp2")
                if not issue:
                  if n=="TCI": rgb8.append(target)
                  anyImageDownloaded=True
          if anyImageDownloaded:
            r[4]=datetime.datetime.now(); update=True
        if update: rows.updateRow(r)
    if not opMode["ImgSel"]:
      sensub.flushline("</metalink>",cartFile); cartFile.close()
      os.rename(cartPart,cartName); arcpy.AddMessage(cartName)
      summary = "Missed %s" % missed
      if opMode["Full"]: summary = "Downloaded %s, Skipped %s, Failed %s, %s" % (dldone,dlskipped,dlfailed, summary)
      arcpy.AddMessage(summary)
    params[self.i["DEMO"]].value = ";".join(demo)
    params[self.i["RGB8"]].value = ";".join(rgb8)

