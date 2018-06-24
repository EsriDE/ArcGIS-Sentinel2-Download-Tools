# -*- coding: UTF-8 -*-

# Copyright 2018 Esri Deutschland GmbH
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
VERSION=20180622
import arcpy,os,sys
HERE=os.path.dirname(__file__); sys.path.append(os.path.join(HERE,"lib"))
try: reload(sensub) # With this, changes to the module's .py file become effective on a toolbox Refresh (F5) from within ArcGIS, i.e. without having to restart ArcGIS.
except NameError: import sensub
sensub.arcpy, sensub.THERE, sensub.SYMDIR = arcpy, HERE, os.path.join(HERE,"lyr")
ARCMAP = arcpy.sys.executable.endswith("ArcMap.exe")
if ARCMAP:
  MXD, CME = arcpy.mapping.MapDocument("CURRENT"), "CopiedMapExtent"
  sensub.MXD, sensub.CME = MXD, CME
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
  w=dict() # Forward warning messages from updateParameters to updateMessages. (Is there a better way to accomplish this?)
  WGS84 = arcpy.SpatialReference("WGS 1984")

  def __init__ (self):
    """Initialize the tool (tool name is the name of the class)."""
    self.label = "Search DHuS catalog" # Displayed name.
    self.description = "Search Data Hub Services' (DHuS) product catalog for Sentinel-2 products (L1C, or L2A where available) according to given criteria (in particular spatiotemporal constraints and cloud cover limit)."
    self.canRunInBackground = False
    if ARCMAP: # Dispose well-known broken in_memory layers:
      try:
        for df in arcpy.mapping.ListDataFrames(MXD):
          for lyr in arcpy.mapping.ListLayers(MXD, CME+"*", df):
            if lyr.isBroken: arcpy.mapping.RemoveLayer(df, lyr)
      except RuntimeError: pass # "Object: CreateObject cannot open map document"! This happens after having edited the "Item Description..." (enforces to restart ArcGIS)!

  def getParameterInfo (self): # Why arcpy always calls getParameterInfo multiple times (up to seven times when a tool is called using arcpy.ImportToolbox("P:/ath/to/File.pyt"))?? Instantiation of each toolbox tool class happens even oftener.
    """Prepare parameter definitions."""
    params=[DHUSUSR,DHUSPWD,DHUSALT]
    PROCLEVEL = arcpy.Parameter("PROCLEVEL", "Processing level", datatype="GPString")
    PROCLEVEL.filter.type="ValueList"; PROCLEVEL.filter.list=["1C","2A"]; params.append(PROCLEVEL)
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
    OPMERGE = arcpy.Parameter("OPMERGE", "Merge new finds with ones from previous searches", datatype="GPBoolean", parameterType="Optional"); params.append(OPMERGE)
    ROWSMAX = arcpy.Parameter("ROWSMAX", "Maximum count of search result rows", datatype="GPLong", parameterType="Optional")
    ROWSMAX.filter.type="Range"; ROWSMAX.filter.list=[1,5000]; params.append(ROWSMAX)
    params.append(arcpy.Parameter("PRODCAT_", datatype="DERasterCatalog", symbology=sensub.dep("Product.lyr"), parameterType="Derived", direction="Output")) # Why direction must/can be specified when "Derived" implicitly enforces "Output"??
#    params.append(arcpy.Parameter("aoiTmp", datatype="DEFeatureClass", symbology=sensub.dep(CME+".lyr"), parameterType="Derived", direction="Output"))
#    params.append(arcpy.Parameter("debug", "debug", datatype="GPString", parameterType="Optional"))
    # Preset:
    sensub.recall(self, params, ["aoiMap","aoiLayer"])
    if PROCLEVEL.value is None: PROCLEVEL.value="1C"
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
    dhusAlt,PROCLEVEL = params[self.i["DHUSALT"]].value, params[self.i["PROCLEVEL"]]
    if not DHUSALT.hasBeenValidated:
      if dhusAlt=="CODE-DE":
        PROCLEVEL.value="1C"; PROCLEVEL.enabled=False
      else: PROCLEVEL.enabled=True

    AOIENV,aoiLayer,aoiMap = params[self.i["AOIENV"]], params[self.i["aoiLayer"]], params[self.i["aoiMap"]]
    if not AOIENV.hasBeenValidated:
      aoiLayer.enabled = AOIENV.enabled = True # Why GPEnvelope's widget allows "Clear" when not being enabled??
      if ARCMAP: aoiMap.enabled=True
      aoiMap.value = False
    elif not aoiMap.hasBeenValidated:
      if aoiMap.value and ARCMAP:
        e = MXD.activeDataFrame.extent
        pe = sensub.projectExtent(self, e, "aoiMap", "Active data frame")
        if pe:
          params[self.i["AOIENV"]].value = pe
          tmpName = "%s%d" % (CME, arcpy.mapping.ListDataFrames(MXD).index(MXD.activeDataFrame))
          tmpSource = os.path.join("in_memory",tmpName)
          fresh=False
          if not arcpy.Exists(tmpSource):
            arcpy.CreateFeatureclass_management("in_memory", tmpName, "POLYGON", spatial_reference=self.WGS84)
            fresh=True
          ll = arcpy.mapping.ListLayers(MXD, tmpName, MXD.activeDataFrame)
          if not ll: arcpy.mapping.AddLayer(MXD.activeDataFrame, arcpy.mapping.Layer(tmpSource), "TOP") # Most notably: Placed above all group layers.
          if fresh or not ll: arcpy.ApplySymbologyFromLayer_management(tmpName, sensub.dep(CME+".lyr"))
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
          dfLayers = (lyr.name for lyr in arcpy.mapping.ListLayers(MXD, data_frame=MXD.activeDataFrame))
          if aoiLayer.valueAsText not in dfLayers:
            self.w["aoiLayer"]="Layer not found in active data frame, nothing copied over."
            dismiss=True
        if not dismiss:
          if hasattr(aoiLayer.value,"dataSource") and aoiLayer.value.dataSource: # "Basemap" has no dataSource attribute! And 'geoprocessing Layer object' has no supports() funtion.
            d = arcpy.Describe(aoiLayer.value.dataSource)
            if d.dataType=="FeatureDataset": self.w["aoiLayer"]="FeatureDataset found, nothing copied over."
            else:
              pe = sensub.projectExtent(self, d.extent, "aoiLayer", "Data source")
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
    sensub.setEnv("PRODCAT", prodCat) # Preset for Download tool.

    e = params[self.i["AOIENV"]].value; aoiEnv = "%f %f %f %f" % (e.XMin,e.YMin,e.XMax,e.YMax)
    sensub.auth(params[self.i["DHUSUSR"]].value, params[self.i["DHUSPWD"]].value, params[self.i["DHUSALT"]].value)
    finds = sensub.search(params[self.i["PROCLEVEL"]].value, params[self.i["SENSINGMIN"]].value, params[self.i["SENSINGMAX"]].value, aoiEnv, 1, params[self.i["CLOUDYMAX"]].value, params[self.i["ROWSMAX"]].value) # OVERLAPMIN currently not implemented, set to a fixed dummy value.
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
          preview,issue,severity = sensub.download(urlFormat%previewPath, tmpDir, "%s.%s.jp2"%(UUID,tileName), slim=True)
          if not issue or issue=="already exists":
            toRemove.add(preview); auxPath=preview+".aux.xml"
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
    params[self.i["PRODCAT_"]].value = prodCat
    #HOWTO "Reload Cache" from arcpy? Is comtypes needed for this?



class Download (object):
  i=dict() # Map parameter name to parameter index; provides 'parameter by name'.
  import collections
  modes = collections.OrderedDict([
    ("CartOnly", "Cart-only (no raster data)"),
    ("Full", "Full product (cart in parallel)"),
    ("ImgSel", "Image selection (bare raster)")]) # Provide displayName (label) by mode name.
  probs = collections.OrderedDict([("CLD","Cloud"), ("SNW", "Snow/Ice")])
  prbNames = probs.keys()
  indices = collections.OrderedDict([
    ("NDWI","NDWI(McFeeters)*"),
    ("MNDWI","*"),
    ("nNDVI","-NDVI*"),
    ("nNDVI_GREEN","-NDVI-GREEN*"),
    ("SWI",None),
    ("WRI","*"),
    ("NWIgreen","NWI(green)*"),
    ("NWIblue","NWI(blue)*"),
    ("MBWI",None),
    ("WI2015","*"),
    ("AWEInsh","*"),
    ("AWEIsh","*"),
    ("SBM2m3_6p2m8p6m11p6m12p2", u"SBM(2•3—6²•8⁶•11⁶•12²)")]) #•⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻—₀₁₂₃₄₅₆₇₈₉⋅Πρᵢ↑xᵢ
  idxFilterable = list()
  for n,dn in indices.iteritems():
    if dn is None: indices[n]=n
    elif dn=="*": indices[n]=n+"*"
    if indices[n].endswith("*"): idxFilterable.append(n)
  idxNames = indices.keys(); idxNames.reverse()
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
    ("B10","(L1C-only) SWIR (cirrus), 1380nm(30nm), 60m"),
    ("B11","SWIR (snow/ice/cloud), 1610nm(90nm), 20m"),
    ("B12","SWIR (snow/ice/cloud), 2190nm(180nm), 20m"),
    ("TCI","Natural color composite (3•8 bit), 10m"),
    # L2A-only:
    ("TCI_20m",None),
    ("TCI_60m",None),
    ("CLD","Cloud confidence, 20m"),
    ("CLD_60m",None),
    ("SNW","Snow/ice confidence, 20m"),
    ("SNW_60m",None),
    ("SCL","Scene Classification, 20m"),
    ("SCL_60m",None),
    ("AOT","Aerosol Optical Thickness (at 550nm), 10m"),
    ("AOT_20m",None),
    ("AOT_60m",None),
    ("WVP","Water Vapour, 10m"),
    ("WVP_20m",None),
    ("WVP_60m",None),
#    ("VIS","(not documented), 20m"), # Extincted with PSD14.5!
    ("B02_20m",None),
    ("B02_60m",None),
    ("B03_20m",None),
    ("B03_60m",None),
    ("B04_20m",None),
    ("B04_60m",None),
    ("B05_60m",None),
    ("B06_60m",None),
    ("B07_60m",None),
    ("B8A_60m",None),
    ("B11_60m",None),
    ("B12_60m",None)])
  imgNames = images.keys()
  outNames,plainFileBased = ["MSIL1C"], ["TCI1C","TCI","SCL","SNW","CLD"]
  outNames += plainFileBased
  arcVersion, saEnabled = arcpy.GetInstallInfo()["Version"], False
  bmfUtility = True if arcVersion>="10.5" else False # With lower arcVersion, the expression parser of BandArithmeticFunction is too picky.
  if ARCMAP:
    try:
      arcpy.sa.Int(1) # Is there a better way to check whether sa is enabled (not to be confused with "available")?
      saEnabled = True
    except RuntimeError as err:
      if not "ERROR 000824" in err.message: raise

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
    catName="  L2A additions (masks, filters, index selection)"
    for n,dn in self.probs.iteritems():
      params.append(arcpy.Parameter(n+"MSK", "Create %s mask layer (according to threshold)"%dn, category=catName, datatype="GPBoolean", parameterType="Optional"))
      params.append(arcpy.Parameter(n+"FLT", "Apply %s filter to selected filterable* indices (according to threshold)"%dn, category=catName, datatype="GPBoolean", parameterType="Optional"))
      threshold = arcpy.Parameter(n+"THR", "%s threshold (probability percentage)"%dn, category=catName, datatype="GPLong", parameterType="Optional")
      threshold.filter.type="Range"; threshold.filter.list=[1,100]; params.append(threshold)
    for n,dn in self.indices.iteritems(): params.append(arcpy.Parameter(n, dn, category=catName, datatype="GPBoolean", parameterType="Optional"))
    catName="Image selection"
    for n,dn in self.images.iteritems():
      dspName = n if dn is None else "%s: %s"%(n,dn)
      params.append(arcpy.Parameter(n, dspName, category=catName, datatype="GPBoolean", parameterType="Optional"))
      if n=="TCI": catName="L2A-only images"
    for on in self.outNames: params.append(arcpy.Parameter(on+"_", datatype="DERasterDataset", multiValue=True, symbology=sensub.dep(on+".lyr"), parameterType="Derived", direction="Output"))
    # Preset:
    sensub.recall(self,params)
    if OPMODE.value is None: OPMODE.value=self.modes["CartOnly"]
    if UNZIP.value is None: UNZIP.value=True
    if params[self.i["CLDTHR"]].value is None: params[self.i["CLDTHR"]].value=40
    if params[self.i["SNWTHR"]].value is None: params[self.i["SNWTHR"]].value=1
    for n in ["TCI"]: #"B04","B03","B02","NDWI"
      I = params[self.i[n]]
      if I.value is None: I.value=True
    return params


  def updateParameters (self, params):
    OPMODE = params[self.i["OPMODE"]] 
    isFull = True if OPMODE.value==self.modes["Full"] else False
    if not OPMODE.hasBeenValidated:
      params[self.i["UNZIP"]].enabled = True if isFull else False
      for n in "CLDMSK","SNWMSK": params[self.i[n]].enabled = isFull and self.saEnabled
      for n in "CLDFLT","SNWFLT": params[self.i[n]].enabled = isFull and self.saEnabled and self.bmfUtility
      for n in self.idxNames: params[self.i[n]].enabled = isFull and self.bmfUtility
      isImgSel = True if OPMODE.value==self.modes["ImgSel"] else False
      for n in self.imgNames: params[self.i[n]].enabled=isImgSel

    for n in self.prbNames:
      mskORflt=False
      for o in "MSK","FLT":
        p = params[self.i[n+o]]
        mskORflt = mskORflt or (p.value and p.enabled)
      params[self.i[n+"THR"]].enabled = mskORflt and isFull


  def updateMessages (self, params):
    RASTERDIR = params[self.i["RASTERDIR"]]
    if RASTERDIR.value:
      rp,MAXLEN = os.path.realpath(RASTERDIR.valueAsText), 11
      if len(rp)>MAXLEN: RASTERDIR.setErrorMessage("%s: Path too long (max. %d characters, incl. drive letter and dir. sep.)." % (rp,MAXLEN))

    OPMODE,errMsg = params[self.i["OPMODE"]], "%s is empty (see list below), please select at least one of them."
    if OPMODE.value==self.modes["ImgSel"] and not sensub.anySelected(self,params,self.imgNames): OPMODE.setErrorMessage(errMsg%"Image selection")
    elif OPMODE.value==self.modes["Full"] and not sensub.anySelected(self,params,self.idxFilterable):
      for n in self.prbNames:
        FLT = params[self.i[n+"FLT"]]
        if FLT.value: FLT.setErrorMessage(errMsg%"Selection of filterable* indices")


  def execute (self, params, messages):
    sensub.memorize(params)
    prodCat = params[self.i["PRODCAT"]].valueAsText
    catName = os.path.basename(prodCat)
    sensub.setEnv("CATNAME", catName); sensub.setEnv("FGDB", os.path.dirname(prodCat)) # Preset for Search tool.
    rasterDir = os.path.realpath(params[self.i["RASTERDIR"]].valueAsText)
    m,opMode = params[self.i["OPMODE"]].value, dict()
    for k in self.modes.keys(): opMode[k] = True if m==self.modes[k] else False
    unzip,out,sym, msk,flt,thr,briefName,symName = params[self.i["UNZIP"]].value, dict(), dict(), dict(),dict(),dict(),dict(),dict()
    for n,dn in self.probs.iteritems(): msk[n],flt[n],thr[n],briefName[n],symName[n] = params[self.i[n+"MSK"]].value, params[self.i[n+"FLT"]].value, params[self.i[n+"THR"]].value, n+"_20m", dn.replace("/","")
    for on in self.outNames: out[on]=list()
    toRestore = list()
    try:
#      cursor = arcpy.da.SearchCursor if opMode["CartOnly"] else arcpy.da.UpdateCursor
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
        dhusAlt = params[self.i["DHUSALT"]].value
        sensub.auth(params[self.i["DHUSUSR"]].value, params[self.i["DHUSPWD"]].value, dhusAlt)
        if opMode["Full"] and unzip:
          if ARCMAP:
            for ln in ["Group","BOA","Gray"]+self.plainFileBased:
              if self.arcVersion>="10.6" or ln!="BOA": sym[ln] = arcpy.mapping.Layer(sensub.dep(ln+".lyr"))
            sensub.SYMGRP,symPath, = sym["Group"], dict()
            for sn in ["Index"]+symName.values(): symPath[sn]=sensub.dep(sn+".lyr")
            sensub.SYMRFT = symPath,"dummy-11.tif" # For RFT-based layers.
            for lyr in arcpy.mapping.ListLayers(MXD, data_frame=MXD.activeDataFrame):
              if lyr.visible and lyr.longName.find("\\")<0: # Only top-level needed.
                lyr.visible=False; toRestore.append(lyr) # Hack to minimize ArcMap's annoying intermediate drawing performances. Why does ArcMap always perform redrawing even if the added layer (or its holding group layer) has visible=False (which means that any redrawing is totally useless anyway)? And why is there no arcpy.mapping.PauseDrawing() available?
        import re
        for r in rows:
          Name,SensingDate,Size,Marked,Downloaded,Title,UUID,MD5 = r
          L2A = sensub.isL2A(Title)
          if L2A and dhusAlt=="CODE-DE":
            arcpy.AddWarning("# %s: CODE-DE does not provide any L2A products!"%Title); continue
          update,procBaseline,PSD13 = False, sensub.baselineNumber(Title), len(Title)==78 # Title length of a product that complies with PSD version < 14.
          if not opMode["ImgSel"]:
            processed,md5sum,issue,severity = (None,MD5,None,0) if not prodMemo.has_key(UUID) else prodMemo.get(UUID)
            if not processed: # Yet unprocessed single-tile package, or first tile occurrence of a multi-tile package (scene) or of a dupes set (should not happen):
              arcpy.AddMessage("# %s, %s (%s)" % (Size, Title, UUID))
              if not md5sum: md5sum,issue,severity = sensub.md5sum(UUID)
              if not md5sum:
                arcpy.AddWarning(" => Missed."); missed += 1
              else:
                m4int = filename,md5sum,url = Title+".zip", md5sum, sensub.SITE["SAFEZIP"]%UUID
                sensub.flushline("  <file name='%s'><hash type='MD5'>%s</hash><url>%s</url></file>" % m4int, cartFile)
                if opMode["Full"]:
                  outcome,issue,severity = sensub.download(url, rasterDir, filename, md5sum, unzip, Title+".SAFE")
                  if not issue or (issue=="already exists" and outcome is not None):
                    if not issue: dldone += 1
                    if unzip: # ILLUSTRATION OF PRESENTATION VARIANTS:
                      # ( ) = Built-in Function Template
                      #  +  = Within Group Layer
                      #  •  = Nonexistent SAFE Package Situation
                      #
                      # Y: Product Level
                      # |__X: ArcGIS Version
                      # \
                      #  Z: PSD Version
                      #
                      #      2A
                      #        \
                      #         •------------•------------•
                      #         |\           |\           |\
                      #         | \          | \          | \
                      #         | TCI+---------TCI+--------(2A)+TCI
                      #         |  |\        |  |\        |  |\
                      #      1C |  | \       |  | \       |  | \
                      #        \|  | TCI+---------TCI+---------TCI+
                      # PSD13-(1C)-|--|----(1C)-|--|----(1C) |  |
                      #          \ |  |       \ |  |       \ |  |
                      #           \|  |        \|  |        \|  |
                      #    PSD14-TCI1C|-------(1C)-|-------(1C) |
                      #             \ |          \ |          \ |
                      #              \|           \|           \|
                      #       PSD14.5-•------------•------------•
                      #               |            |            |
                      #               10.4.1       10.5.1       10.6
                      #               10.5
                      safeDir,mtdName = outcome; mtdFull=os.path.join(safeDir,mtdName)
                      if PSD13 or (self.arcVersion>="10.5.1" and not L2A): out["MSIL1C"].append(os.path.join(mtdFull,"Multispectral-10m")) # Built-in function template as part of built-in L1C raster product support.
                      else: # Remaining PSD14-related cases:
                        with open(mtdFull) as f:
                          tci = re.search(r"GRANULE/[^/]+/IMG_DATA/(R10m/(L2A_)?)?T\w+_TCI(_10m)?", f.read())
                          if tci:
                            relPath = tci.group(0)
                            if L2A: relPath = relPath.replace("IMG_DATA/R10m","%s",1).replace("TCI_10m","%s",1)
                            imgFull = os.path.join(safeDir, relPath+".jp2")
                            if not L2A: out["TCI1C"].append(imgFull) # PSD14 not supported with ArcGIS version < 10.5.1
                            else: # Grouping of various L2A layers:
                              if ARCMAP:
                                X,reference,refMain,grpName = dict(), (None,None), dict(), re.sub(".+(L2A_)(.+)_N.+_(T\d{1,2}[A-Z]{3}_).+", r"\3\2", Title) # Naming convention similar to L2A .jp2 file names.
                                if self.arcVersion>="10.6" and procBaseline<="0206": reference = sensub.insertIntoGroup(os.path.join(mtdFull,"BOA Reflectance-10m"), reference, grpName, sym["BOA"], "BOA 10m") # Incorporate built-in L2A raster product demo.
                                for n in "TCI_10m","SCL_20m","SNW_20m","CLD_20m":
                                  X[n] = sensub.imgPath(imgFull,n,procBaseline)
                                  reference = refMain[n] = sensub.insertIntoGroup(X[n], reference, grpName, sym[n[:3]])
                                # For the following, ignore self.saEnabled, since a currently missing Spatial Analyst license can be (re-)enabled by the user at any time:
                                for n,dn in self.probs.iteritems():
                                  if msk[n]: sensub.insertIntoGroup(("mask",(X[briefName[n]],thr[n],symName[n])), refMain[briefName[n]], grpName, altName=dn)
                                if self.bmfUtility:
                                  reference,anyIndex,B = refMain["SCL_20m"], False, dict()
                                  for bn in "02","03","04","05","06","07","08","11","12":
                                    name = "B"+bn
                                    B[bn] = sensub.imgPath(imgFull, name, label=self.images[name])
                                  for n in self.idxNames:
                                    showIndex = params[self.i[n]].value
                                    if showIndex: anyIndex=True
                                    reference = sensub.insertIntoGroup((n,(B,X,(flt,thr))), reference, grpName, altName=self.indices[n], skip = not showIndex)
                                  if anyIndex: sensub.insertIntoGroup(B["08"], refMain["TCI_10m"], grpName, sym["Gray"]) # For visual (water) index assessment.
                  if severity==1:
                    arcpy.AddWarning(" => Skipped."); dlskipped += 1
                  elif severity>1:
                    if issue.startswith("cannot reach"): missed += 1
                    else: dlfailed += 1
              processed = datetime.datetime.now()
            if not MD5 and md5sum:
              r[7]=md5sum; update=True # Cache it to avoid potentially redundant checksum calls.
            if opMode["Full"] and not issue:
              r[4]=processed; update=True
            prodMemo[UUID] = processed,md5sum,issue,severity
          elif Marked:
            tileName = Name.split()[0]
            arcpy.AddMessage("# %s, %s," % (Title,tileName))
            if not prodMemo.has_key(UUID): prodMemo[UUID] = sensub.prodTiles(Title,UUID,SensingDate,False,L2A,procBaseline)
            tiles,urlFormat = prodMemo.get(UUID)
            if urlFormat is None: arcpy.AddWarning(" => Missed.")
            else:
              tileDir = os.path.join(rasterDir, Title, tileName)
              if not os.path.exists(tileDir): os.makedirs(tileDir)
              any = {"downloaded":False}
              for on in self.plainFileBased: any[on]=False
              for n,dn in self.images.iteritems():
                if params[self.i[n]].value:
                  i = self.imgNames.index(n)
                  if n=="TCI" and PSD13: arcpy.AddWarning("  %s: not available for older products (PSD<14)."%n)
                  elif n=="B10" and L2A: pass #arcpy.AddWarning("  %s: not available for L2A products."%n)
                  elif i<14 or L2A:
                    arcpy.AddMessage("  %s" % n)
                    pathFormat = tiles[tileName]
                    imgPath = sensub.imgPath(pathFormat, n, procBaseline, L2A, dn)
                    if L2A: imgPath=sensub.plain2nodes(imgPath) # Catch-up.
                    imgFull,issue,severity = sensub.download(urlFormat % imgPath, tileDir, n+".jp2")
                    if not issue or (issue=="already exists" and imgFull is not None):
                      for on in self.plainFileBased:
                        if not any[on] and ((not L2A and on=="TCI1C" and n=="TCI") or (L2A and n.startswith(on))):
                          out[on].append(imgFull); any[on]=True; break # Highest resolution rules.
                      if not issue: any["downloaded"]=True
              if any["downloaded"]:
                r[4]=datetime.datetime.now(); update=True
          if update: rows.updateRow(r)
      if not opMode["ImgSel"]:
        sensub.flushline("</metalink>",cartFile); cartFile.close()
        os.rename(cartPart,cartName); arcpy.AddMessage(cartName)
        summary = "Missed %s" % missed
        if opMode["Full"]: summary = "Downloaded %s, Skipped %s, Failed %s, %s" % (dldone,dlskipped,dlfailed, summary)
        arcpy.AddMessage(summary)
      for on in self.outNames: params[self.i[on+"_"]].value = ";".join(out[on])
    finally:
      if toRestore:
        for lyr in toRestore: lyr.visible=True
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
 
