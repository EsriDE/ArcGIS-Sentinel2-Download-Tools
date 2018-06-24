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

"""Common utilities & helper functions for Sentinel geoprocessing tools."""
VERSION=20180622
ROWSSTEP=100 # Ultimate DHuS pagination page size limit (rows per page).
AWS="http://sentinel-s2-l1c.s3.amazonaws.com/"
AOIDEMO="7.58179313821144 51.93624645888022 7.642306784531163 51.968128265779484" # Münster.
PARTIAL=".partial"
import os,urllib2,json,datetime,time,re
import xml.etree.cElementTree as ET
arcpy = THERE = MXD = CME = SYMDIR = SYMGRP = SYMRFT = None # Will be set by the importing module.


SITE=dict()
def auth (usr, pwd, dhusAlt=None):
  """Globally install Basic Auth, and set site specific string constants."""
  SITE["NAME"] = dhusAlt if dhusAlt is not None else "SciHub"
  site,collspec = "https://scihub.copernicus.eu/", "(producttype:S2MSI%s)"
  if SITE["NAME"]=="CODE-DE": site,collspec = "https://code-de.org/", "platformname:Sentinel-2"
  SITE["BASE"] = site+"dhus/"
#  pm=urllib2.HTTPPasswordMgrWithDefaultRealm()
#  pm.add_password(None, SITE["BASE"], usr, pwd)
#  urllib2.install_opener(urllib2.build_opener(urllib2.HTTPBasicAuthHandler(pm)))
#...does not work transparently in combination with proxy support => workaround: urlOpen().
  import base64; SITE["AUTH"] = "Basic " + base64.b64encode("%s:%s" % (usr, pwd))
  SITE["SEARCH"] = SITE["BASE"] + "search?format=xml&sortedby=beginposition&order=desc&rows=%d&q=%s" % (ROWSSTEP, collspec)
  product = SITE["BASE"] + "odata/v1/Products('%s')/"
  SITE["CHECKSUM"], SITE["SAFEZIP"], SITE["SAFEROOT"] = product+"Checksum/Value/$value", product+"$value", product+"Nodes('%s.SAFE')/"

def urlOpen (url):
  """Work around flawed chain of handlers regarding BasicAuth via Proxy."""
  req = urllib2.Request(url)
  if url.startswith(SITE["BASE"]): req.add_header("Authorization", SITE["AUTH"])
  return urllib2.urlopen(req)

def search (procLevel, sensingMin, sensingMax=None, aoiEnv=AOIDEMO, overlapMin=None, cloudyMax=None, rowsMax=ROWSSTEP):
  """Formulate & run a catalog query."""
  finds = dict()
  if rowsMax <=0: return finds
  if procLevel=="2A": procLevel="2Ap+OR+producttype:S2MSI2A" # 2Ap pilot collection (holding products dated before 2018-03-26), plus the 2A operative collection (products from 2018-03-26 onwards).
  url = SITE["SEARCH"] % procLevel if SITE["NAME"]!="CODE-DE" else SITE["SEARCH"]
  latest = "NOW" if sensingMax is None else sensingMax.isoformat()+"Z" # Z for Zulu, UTC.
  url += "+AND+beginPosition:[%s+TO+%s]"%(sensingMin.isoformat()+"Z", latest)
  spatOp = "Contains" if overlapMin is not None and overlapMin>=100 else "Intersects" # Currently, DHuS OpenSearch (solr) does not implement "Overlaps"!
  XMin,YMin,XMax,YMax = aoiEnv.split()
  rect = "%s+%s,%s+%s,%s+%s,%s+%s,%s+%s" % (XMin,YMin, XMin,YMax, XMax,YMax, XMax,YMin, XMin,YMin)
  url += "+AND+footprint:%22"+spatOp+"(POLYGON(("+rect+")))%22"
  if cloudyMax is not None: url += "+AND+cloudCoverPercentage:[0+TO+%d]"%cloudyMax
  url += "&start="
  notify(url)
  # Let's go for it:
  offset,rowsBreak = 0,rowsMax
  while offset<rowsBreak: # Next page:
    if offset>0: notify("...offset: %d" % offset)
    rsp = urlOpen(url + str(offset))
    root=ET.ElementTree(file=rsp).getroot(); ns={"atom":"http://www.w3.org/2005/Atom", "opensearch":"http://a9.com/-/spec/opensearch/1.1/"}
    if offset==0: # First page:
      found = int(root.find("opensearch:totalResults",ns).text)
      txt = "Products found: %d" % found
      if found>rowsMax: txt += ", trimmed to (user wanted) %d"%rowsMax
      else: rowsBreak = found
      notify(txt)
    for e in root.iterfind("atom:entry",ns):
      if len(finds)>=rowsBreak: break
      sensingZulu = e.find("atom:date[@name='beginposition']",ns).text[:19] # With PSD version >=14, the date string has millis appended.
      cloudy = float(e.find("atom:double[@name='cloudcoverpercentage']",ns).text)
      finds[e.find("atom:id",ns).text] = e.find("atom:title",ns).text, datetime.datetime.strptime(sensingZulu, "%Y-%m-%dT%H:%M:%S"), cloudy, e.find("atom:str[@name='size']",ns).text
    offset += ROWSSTEP
  return finds

def isL2A (name):
  """Check if name belongs to a L2A product."""
  return True if name.find("L2A_")>0 else False

def baselineNumber (Title):
  """Extract the processing baseline number from the given product title."""
  return re.sub(r".+_N(\d{4})_.+", r"\1", Title)

def plain2nodes (path):
  """Convert whole plain path to DHuS-specific Nodes path."""
  return re.sub("([^/]+)", r"Nodes('\1')", path)

def useDHuS (Title, UUID, preview, L2A, procBaseline):
  """Provide prodTiles using DHuS."""
  tiles,safeRoot = dict(), SITE["SAFEROOT"]%(UUID,Title)
  url = safeRoot + "Nodes('manifest.safe')/$value" # Regarding any pilot phase L2A product (<="0206"), this is still the L1C manifest!
  rsp,issue,severity = catch500(url)
  if rsp:
    info = rsp.read()
    GRANULE = r"GRANULE/[^/]+_T(\d{1,2}[A-Z]{3})_[^/]+/%s_DATA/[^.]+%s\.jp2"
    pat = GRANULE%("QI","_PVI") if preview else GRANULE%("IMG","_B02(_10m)?")
    for m in re.finditer(pat,info):
      path = m.group()
      if L2A:
        prefix=""
        if procBaseline<="0206": path,prefix = path.replace("L1C_","L2A_",1), "L2A_" # Pilot phase specific.
        if not preview: path = re.sub("IMG_DATA/(R10m/)?", "%s/"+prefix, path)
      if not preview: path = re.sub("_B02(_10m)?", "_%s", path)
      if not (not preview and L2A): path = plain2nodes(path) # Else caught up at a downstream stage (because of multiple preparatory interim interpolations).
      tiles[m.group(1)] = path
  return tiles, safeRoot+"%s/$value"

def prodTiles (Title, UUID, Sensing, preview=True, L2A=None, procBaseline=None):
  """Resolve product's tile(s) image path(s)."""
  if L2A is None: L2A=isL2A(Title)
  if procBaseline is None: procBaseline=baselineNumber(Title)
  if L2A:
    if not preview: return useDHuS(Title, UUID, preview, L2A, procBaseline) # Currently, AWS does not provide any L2A images.
    elif procBaseline>"0206": return useDHuS(Title, UUID, preview, L2A, procBaseline) # Now provides a proper BOA preview.
    # Any pilot phase L2A product (<="0206") doesn't come with a properly(!) georeferenced BOA preview, therefore the corresponding L1C (TOA) preview must then be used.
  try:
    url = "%sproducts/%d/%d/%d/%s/productInfo.json" % (AWS, Sensing.year,Sensing.month,Sensing.day, Title.replace("L2A_","L1C_",1))
    info = json.load(urllib2.urlopen(url))
    imgName = "preview" if preview else "%s"
    tiles = dict()
    for t in info["tiles"]: tiles["%d%s%s" % (t["utmZone"], t["latitudeBand"], t["gridSquare"])] = "%s/%s.jp2" % (t["path"], imgName)
    urlFormat = AWS+"%s"
  except urllib2.HTTPError as err:
    if err.code==404: # Why are some product paths not valid? For example: products/2016/7/20/S2A_OPER_PRD_MSIL1C_PDMC_20160805T152827_R051_V20160720T105547_20160720T105547/productInfo.json
      notify("%s: Missing product info on AWS, using DHuS as fallback..."%Title, 1)
      tiles,urlFormat = useDHuS(Title, UUID, preview, L2A, procBaseline)
    else: raise
  return tiles,urlFormat


def catch500 (url):
  """Catch error when (typically) OData resource is non-existent."""
  rsp,issue,severity = None,None,0
  try: rsp = urlOpen(url)
  except urllib2.HTTPError as err:
    if err.code==500:
      issue="cannot reach (non-existent?)"; severity=notify("%s: %s!"%(url,issue), 2)
    else: raise
  return rsp,issue,severity

def md5sum (UUID):
  """Retrieve MD5 hash for the product with given UUID."""
  notify("Retrieving MD5 hash...")
  md5sum=None
  rsp,issue,severity = catch500(SITE["CHECKSUM"]%UUID)
  if rsp: md5sum = rsp.read()
  return md5sum,issue,severity

def refine (tentative):
  """Convert tentative outcome to a more specific path if applicable."""
  ultimate=None
  if os.path.exists(tentative):
    if tentative.endswith(".SAFE"):
      mtd = filter(re.compile(r"MTD_.+\.xml").search, os.listdir(tentative))
      if mtd: ultimate=(tentative, mtd[0]) # The product's XML-based main definition.
    else: ultimate=tentative # Plain single image file.
  return ultimate

KiB=1024; MiB=KiB**2
def download (url, folder=os.environ["TEMP"], filename=None, md5sum=None, unzip=False, unzipName=None, slim=False):
  """Download resource content to file in folder, where filename may implicitly be given by resource MIME header.
  Optionally check MD5 sum and/or unzip file content to folder (where appropriate)."""
  issue,severity = None,0
  folder = os.path.realpath(folder) # Paranoid.
  if not os.path.isdir(folder):
    issue="not a directory"; severity=notify("%s: %s!"%(folder, issue), 1)
    return folder,issue,severity
  rsp=None
  if not filename: # As a fallback, check MIME header:
    rsp = urlOpen(url)
    cd = rsp.headers.getheader("Content-Disposition")
    if cd:
      import cgi
      par = cgi.parse_header(cd)[1]
      fn=par.get("filename")
      if fn: filename=par["filename"]
  if not filename: filename="unknown" # Last resort.
  filename = os.path.basename(filename) # Paranoid.
  target = wanted = os.path.join(folder, filename)

  # Do not overwrite:
  toCheck=[target]
  if slim: tmp=target
  else:
    tmp=target+PARTIAL; toCheck.append(tmp)
  if unzip:
    wanted = folder # Dummy so far.
    if unzipName is not None: unzipName = os.path.basename(unzipName).strip() # Paranoid.
    if unzipName:
      wanted=os.path.join(folder,unzipName.strip()); toCheck.append(wanted)
  for f in toCheck:
    if os.path.exists(f):
      issue="already exists"; severity=notify("%s: %s!"%(f, issue), 1)
  if issue: return refine(wanted),issue,severity

  if not rsp: rsp,issue,severity = catch500(url)
  if not rsp: return url,issue,severity
  cl = rsp.headers.getheader("Content-Length")
  size = int(cl) if cl else -1
  if size>-1 and not slim: # Check free disk space:
    import ctypes
    free = ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free))
    estimated = size if not unzip else 2.5*size
    if free.value<estimated:
      issue="not enough space"; severity=notify("%s: %s, free is %d MiB but estimated need is %d MiB!"%(folder, issue, int(round(free.value/MiB)), int(round(estimated/MiB))), 1)
      return folder,issue,severity

  # Actually fetch now:
  if md5sum:
    import hashlib
    md5hash=hashlib.md5()
  with open(tmp,"wb") as f:
    if slim: f.write(rsp.read())
    else: # Do not read as a whole into memory:
      notify("Downloading %s <<< %s" % (target,url))
      written=0
      if arcpy:
        progType = "step" if size>0 else "default"
        arcpy.SetProgressor(progType, target)
      started = updated = datetime.datetime.now()
      for block in iter(lambda:rsp.read(8192),""): # urllib.retrieve() has 8KiB as default block size, shutil.copyfileobj() 16KiB.
        f.write(block); written += len(block)
        meantime = datetime.datetime.now()
        if (meantime-updated).total_seconds() >1:
          print written
          if arcpy:
            arcpy.SetProgressorLabel("%d KiB" % round(written/KiB))
            if progType=="step": arcpy.SetProgressorPosition(int(round(written*100/size)))
          updated=meantime
        if md5sum: md5hash.update(block)
  written = os.path.getsize(tmp)
  if not slim:
#    if arcpy: arcpy.ResetProgressor()
    if arcpy and progType=="step": arcpy.SetProgressorPosition(100)
    elapsed = (datetime.datetime.now() - started).total_seconds()
    average = "" if elapsed==0 else ", average %s KiB/s" % round(written/KiB/elapsed,2)
    notify("[written/size = %d/%d%s]" % (written,size, average))

  # Verify:
  if size>-1 and written!=size:
    issue="size mismatch"; severity=notify("%s: %s, %d bytes written but expected %d bytes to write!"%(tmp, issue,written,size), 2)
  if not issue and md5sum:
    calculated,expected = md5hash.hexdigest(), md5sum.lower()
    if calculated!=expected:
      issue="MD5 mismtach"; severity=notify("%s: %s, calculated %s but expected %s!"%(tmp, issue,calculated,expected), 2)
  if issue: return tmp,issue,severity

  if not slim: os.rename(tmp,target)
  if unzip:
    import zipfile
    if not zipfile.is_zipfile(target):
      issue="not a zip file"; severity=notify("%s: %s!"%(tmp, issue), 2)
      return target,issue,severity
    notify("Unzipping...")
    pathTooLong = False
    with zipfile.ZipFile(target) as z: # z.extractall(folder) is broken because it doesn't retain the mtime! Workaround:
      for i in z.infolist():
        rp=os.path.realpath(os.path.join(folder, i.filename)); l=len(rp)
        if l>259:
          pathTooLong = True
          notify("%s: Path too long, has %d characters (limit is 259 characters incl. drive letter and directory separators), ZIP item skipped (please extract manually)." % (rp,l), 1) # Windows limit, excl. final null character.
        else:
          rp=z.extract(i,folder)
          if os.path.isfile(rp): # Repair wrong mtime:
            tics = time.mktime(i.date_time + (0,0,-1))
            os.utime(rp, (tics,tics))
    if not pathTooLong: os.remove(z.filename)
    wanted = refine(wanted)
  return wanted,issue,severity


def sql (pythonSet):
  """Make a SQL string from a python set of UUIDs."""
  return re.sub("^set|[u \[\]]", "", str(pythonSet))

def flushline (line, file):
  """Ensure that written lines are not getting lost."""
  print >>file, line
  file.flush()

def notify (msg, severity=0):
  """Forward message to stdout, as well to arcpy messaging (if available)."""
  print msg
  if arcpy: (arcpy.AddMessage,arcpy.AddWarning,arcpy.AddError)[severity](msg)
  return severity

def dep (name, folder=None):
  """By reason of essential dependency, check for existence / readability of the base-named file (in folder)."""
  if not folder: folder=SYMDIR
  fullpath = os.path.join(folder, name)
  with open(fullpath): pass
  return fullpath

def setEnv (name, text):
  """Set named environment variable to given text value."""
  if text:
    try: os.environ[name]=text.encode("UTF-8")
    except: pass # Possibly UnicodeError? Or Paranoid?
  elif os.environ.has_key(name): del os.environ[name]

def recall (tool, params, exclusion=list()):
  """Pull parameter settings from process environment.
  Besides, populate tool's parameter map (name->index), providing 'parameter by name'."""
  for i,p in enumerate(params):
    if p.parameterType!="Derived" and p.name not in exclusion: p.value=os.getenv(p.name) # Possibly encoding issue (when getting "?" chars with Python2.7)?
    tool.i[p.name]=i

def memorize (params):
  """Push parameter settings as presets into process environment.
  Becomes effective on a subsequent script execution when you have evoked a Refresh (F5) on the respective toolbox icon beforehand (from within ArcGIS Desktop)."""
  for p in params:
    if p.parameterType!="Derived": setEnv(p.name, p.valueAsText)

def anySelected (tool, params, names):
  """Determine if any tool's named parameter value evaluates to True."""
  anyTrue=False
  for n in names:
    if params[tool.i[n]].value: anyTrue=True
  return anyTrue

def hasNext (rows):
  """Check if a cursor yields a next item.""" # Why arcpy cursors doesn't have this built in?
  hasOne=True
  try: rows.next()
  except StopIteration: hasOne=False # Why does it not just return None instead of raising this annoying exception?
  finally: rows.reset()
  return hasOne

def dayStart (origin):
  """Reset datetime's time part to start of the day (i.e. 00:00:00)."""
  return datetime.datetime(origin.year, origin.month, origin.day)

def enforceDateOnly (param):
  """Validate GPDate very generally."""
  # Is there any GPDate parameter option to enforce 'Date only' in advance, i.e. to disable 'Date and Time' and 'Time only'??
  # See also https://geonet.esri.com/thread/100190
  #   "Is there a way to limit the Date date type to Date only ie limit the Calendar date format radial buttons?"
  if param.value and param.valueAsText.find(":")>0:
    param.setWarningMessage("Please restrict to 'Date only'.")
    param.value = dayStart(param.value.date())

def projectExtent (tool, extent, name, origin):
  """Get projected extent (for designated named parameter) if originating extent is defined."""
  if not extent.spatialReference or extent.spatialReference.name=="Unknown": tool.w[name] = origin+": Unknown spatial reference, nothing copied over."
  else: return str(extent.projectAs(tool.WGS84))


def imgPath (format, name, procBaseline=None, L2A=True, label=None):
  """Interpolate a path format to a name-dependent path."""
  if not L2A: return format % name
  grdRes = name[-3:] if len(name)>3 else label[-3:]
  briefName = name if len(name)>3 else "%s_%s" % (name,grdRes)
  subDir = "IMG_DATA/R"+grdRes
  if name.startswith("CLD") or name.startswith("SNW"):
    subDir = "QI_DATA"
    if procBaseline>"0206": format,briefName = os.path.dirname(format)+"/MSK_%s.jp2", briefName.replace("_","PRB_") # Completely different now.
  return format % (subDir,briefName)

def insertIntoGroup (src, reference, grpName, sym=None, altName=None, skip=False):
  """To named group (within active data frame of current map document; if non-existent, add it beforehand), insert new participant layer (if not already existent) with given data source and given symbology layer (and optional alternative layer name)."""
  (grpLayer,refLayer), lyrName,workspacePath,datasetName,plain = reference, None,None,None,False
  if sym: # ...in contrast to a script-generated function chain layer (see below).
    workspacePath,datasetName = os.path.dirname(src), os.path.basename(src)
    lyrName,plain = datasetName, datasetName.endswith(".jp2")
    if plain:
      lyrName = lyrName.replace("L2A_","")[:-4] # Strip off uninteresting prefix and suffix.
      if lyrName.startswith("MSK_"): lyrName = grpName + lyrName.replace("MSK_"," ").replace("PRB_"," ") # Make it unique.
  if altName: lyrName = "%s %s"%(grpName,altName)
  lyrName = lyrName.rstrip("*") # The name's filterable* indicator (asterisk) is not meant to be a wildcard!
  participant = arcpy.mapping.ListLayers(MXD, lyrName, MXD.activeDataFrame)
  if skip: return reference if not participant else (grpLayer,participant[0])
  if not participant:
    notify("  "+lyrName)
    if sym:
      if not plain: # Part of raster product (in contrast to a plain raster file):
        workspacePath,datasetName = os.path.dirname(workspacePath), os.path.join(os.path.basename(workspacePath),datasetName)
      sym.replaceDataSource(workspacePath, "RASTER_WORKSPACE", datasetName)
    else: sym = globals()[src[0]](*src[1]) # Actual layer generation only now.
    if lyrName.find("_TCI_")<0: sym.visible=False # Alternatively controllable/controlled by the respective .lyr file.
    sym.name = lyrName
    if not grpLayer:
      listed = arcpy.mapping.ListLayers(MXD, grpName, MXD.activeDataFrame)
      if listed: grpLayer = listed[0]
    if not grpLayer: # On-the-fly creation:
      SYMGRP.name = grpName
      cme = arcpy.mapping.ListLayers(MXD, CME+"*", MXD.activeDataFrame)
      if cme: arcpy.mapping.InsertLayer(MXD.activeDataFrame, cme[0], SYMGRP, "AFTER") # Place below.
      else: arcpy.mapping.AddLayer(MXD.activeDataFrame, SYMGRP) # AUTO_ARRANGE.
      grpLayer = arcpy.mapping.ListLayers(MXD, grpName, MXD.activeDataFrame)[0]
    # Progress bottom-up:
    if not refLayer: arcpy.mapping.AddLayerToGroup(MXD.activeDataFrame, grpLayer, sym, "BOTTOM")
    else: arcpy.mapping.InsertLayer(MXD.activeDataFrame, refLayer, sym) # Stacked above refLayer.
    participant = arcpy.mapping.ListLayers(MXD, lyrName, MXD.activeDataFrame)
  return grpLayer,participant[0]


# Raster Function Template (RFT) helper:
def el (name, content):
  """Write a XML element with given element tag name (incl. element attributes) and the element's inner content."""
  return "<%s>%s</%s>" % (name, content, name.partition(" ")[0])

def typedVal (value, type=None):
  """Write a Value element of given type."""
  if type is None: type = "xs:int" if isinstance(value,int) else "xs:string"
  return el("Value xsi:type='%s'"%type, value)

def rasterItem (fdsp, tag="Value", id=None):
  """Write a Raster* element whose source is either a raster function output or a raster dataset on disk or a raster scalar or a prefab rasterItem (target or reference)."""
  fdspStr = True if isinstance(fdsp, basestring) else False
  if fdspStr and fdsp.startswith("<%"): return fdsp%(tag,tag) # Finalization of a prefab rasterItem.
  if fdspStr:
    if fdsp.startswith("<"): type,content = "FunctionTemplate", fdsp
    else: type,content = "DatasetName", el("WorkspaceName xsi:type='typens:WorkspaceName'",
      el("PathName", os.path.dirname(fdsp)) +
      el("WorkspaceFactoryProgID", "esriDataSourcesRaster.RasterWorkspaceFactory.1")
    ) + el("Name", os.path.basename(fdsp))
  else: type,content = "FunctionVariable", typedVal(typedVal(fdsp, "xs:double"), "typens:Scalar")
  prefab = True if id is not None else False
  tag = "%s" if prefab else tag
  name = tag + " xsi:type='typens:Raster%s'"%type
  if not prefab: return el(name,content)
  xtra = " %s"+"='ID%d'"%id
  return el(name+xtra%"id",content), el(name+xtra%"href","") # target,reference

def rasterArray (rasters):
  """Write an array of raster items."""
  return el("Value xsi:type='typens:ArrayOfArgument'", "".join([rasterItem(each,"Argument") for each in rasters]))

def namedArgs (funcName, **kwargs):
  """Write an overall function arguments element that holds all function's named argument values (derived from given key-worded arguments)."""
  return el("Arguments xsi:type='typens:%sFunctionArguments'"%funcName,
    el("Names xsi:type='typens:ArrayOfString'", "".join([el("String",name) for name in kwargs.keys()])) +
    el("Values xsi:type='typens:ArrayOfAnyType'", "".join([el("AnyType xsi:type='typens:RasterFunctionVariable'", val) for val in kwargs.values()]))
  )

def f (name, type, args):
  """Write a named function element with given output type and the function's arguments."""
  return el("Function xsi:type='typens:%s'"%(name+"Function"), el("PixelType",type)) + args

def CompositeBand (type, *rasters):
  """Analogous to ArcGIS' homonymous function."""
  return f("CompositeBand", type, el("Arguments xsi:type='typens:RasterFunctionVariable'", rasterArray(rasters) ))

def BandArithmetic (raster, expression, method="User Defined", type="F32"):
  """Analogous to ArcGIS' homonymous function."""
  methods = {"User Defined":0, "NDVI":1}
  return f("BandArithmetic", type, namedArgs("BandArithmetic", Raster=rasterItem(raster), Method=typedVal(methods[method]), BandIndexes=typedVal(expression)))

def Resample (raster, size=10, method="Cubic Convolution", type="F32"):
  """Analogous to ArcGIS' homonymous function."""
  methods = {"Nearest Neighbor":0, "Bilinear Interpolation":1, "Cubic Convolution":2, "Bilinear Interpolation Plus":4}
  return f("Resample", type, namedArgs("Resample", Raster=rasterItem(raster), ResamplingType=typedVal(methods[method]), OutputCellsize=typedVal(el("X",size)+el("Y",size),"typens:PointN")))

def Remap (raster, min=-1e+38, max=0, type="F32"):
  """Analogous to ArcGIS' homonymous function."""
  return f("Remap", type, namedArgs("Remap", Raster=rasterItem(raster), NoDataRanges=typedVal(el("Double",min)+el("Double",max),"typens:ArrayOfDouble"), InputRanges=typedVal("","typens:ArrayOfDouble"), OutputValues=typedVal("","typens:ArrayOfDouble")))

def ColorspaceConversion (raster, method="RGB2HSV", type="U8"):
  """Analogous to ArcGIS' homonymous function."""
  methods = {"RGB2HSV":0, "HSV2RGB":1}
  return f("ColorspaceConversion", type, namedArgs("ColorspaceConversion", Raster=rasterItem(raster), ConversionType=typedVal(methods[method])))

def Local (type, method, *rasters):
  """Analogous to ArcGIS' homonymous function."""
  methods = {"Times":3, "Boolean And":17, "Greater Than":28, "Greater Than Equal":29, "Less Than":33, "Less Than Equal":34}
  return f("Local", type, namedArgs("Local", Operation=typedVal(methods[method]), Rasters=rasterArray(rasters) ))

def layer (chain, symName):
  """Create a raster layer (incl. named symbology) for the given raster function chain."""
  import time
  rftFull = os.path.join(os.path.realpath(os.environ["TEMP"]), "%f.rft.xml"%time.time())
  with open(rftFull,"w") as tmp: tmp.write(el("RasterFunctionTemplate xsi:type='typens:RasterFunctionTemplate' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance' xmlns:xs='http://www.w3.org/2001/XMLSchema' xmlns:typens='http://www.esri.com/schemas/ArcGIS/10.4'", chain).encode("UTF-8"))
  sym = arcpy.mapping.Layer(SYMRFT[0][symName]) # Unique instance.
  sym.replaceDataSource(SYMDIR, "RASTER_WORKSPACE", SYMRFT[1])
  arcpy.EditRasterFunction_management(sym, function_chain_definition=rftFull)
  os.remove(rftFull)
  return sym

def index (chain, finish="Cubic Convolution", filter=None):
  """Create an index layer for the given raster function chain, with optional finishing resampling and filtering (and implicit remapping) applied."""
  if finish: chain = Resample(chain, 5, finish)
  if filter:
    X,fltthr = filter
    flt,thr = fltthr
    fltFunctions,effect = list(), None
    for n,toDo in flt.iteritems():
      if toDo: fltFunctions.append(Local("U8", "Less Than", Resample(X[n+"_20m"],5), thr[n]))
    if len(fltFunctions)==1: effect=fltFunctions[0]
    elif len(fltFunctions)>1: effect=Local("U8", "Boolean And", *fltFunctions) # Does this still work with more than two fltFunctions?
    if effect: chain = Local("F32", "Times", chain, effect)
  return layer(Remap(chain), "Index")

def mask (raster, threshold, symName):
  """Highlight those raster pixels that reach/exceed the given threshold."""
  return layer(Local("U8", "Greater Than Equal", Resample(raster,5), threshold), symName)


def NDWI (B,X,fltthr): return index(BandArithmetic(Resample(CompositeBand("U16", B["03"], B["08"]),5), "(b1-b2)/(b1+b2) -8/100"), None, (X,fltthr))

def MNDWI (B,X,fltthr): return index(BandArithmetic(CompositeBand("F32", B["03"], Resample(B["11"])), "(b1-b2)/(b1+b2) -8/100"), filter=(X,fltthr))

def nNDVI (B,X,fltthr): return index(BandArithmetic(Resample(CompositeBand("U16", B["04"], B["08"]),5), "(b1-b2)/(b1+b2) -3/100"), None, (X,fltthr))

def nNDVI_GREEN (B,X,fltthr): return index(BandArithmetic(Resample(CompositeBand("U16", B["03"], B["04"], B["08"]),5), "b1*(b2-b3)/(b2+b3)"), None, (X,fltthr))

def SWI (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("U16", ColorspaceConversion(X["TCI_10m"]), B["08"]), "(b2/255 - 7*b4/10000)/(b2/255 + 7*b4/10000) -12/100"), "Bilinear Interpolation")

def WRI (B,X,fltthr): return index(BandArithmetic(CompositeBand("F32", B["03"], B["04"], B["08"], Resample(B["11"])), "(b1+b2)/(b3+b4) -110/100"), filter=(X,fltthr))

def NWIgreen (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["03"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(b1 - b2-b3-b4)/(b1 + b2+b3+b4) +40/100"), filter=(X,fltthr))

def NWIblue (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["02"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(b1 - b2-b3-b4)/(b1 + b2+b3+b4) +45/100"), filter=(X,fltthr))

def MBWI (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["03"], B["04"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(2*b1 - b2 - b3 - b4 - b5)/10000 +8/100"))
#+5,+8,+12,+15,+20

def WI2015 (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["03"], B["04"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(17204 + 171*b1 + 3*b2 -70*b3 - 45*b4 - 71*b5)/10000 -60/100"), filter=(X,fltthr))

def AWEInsh (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["03"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(4*(b1-b3) - (b2 + 11*b4)/4)/10000"), filter=(X,fltthr))

def AWEIsh (B,X,fltthr):
  return index(BandArithmetic(CompositeBand("F32", B["02"], B["03"], B["08"], Resample(CompositeBand("U16", B["11"], B["12"]))), "(b1 + (5*b2 - 3*(b3+b4))/2 - b5/4)/10000"), filter=(X,fltthr))

def SBM2m3_6p2m8p6m11p6m12p2 (B,X,fltthr):
  """Working title: Pine"""
  return index(BandArithmetic(CompositeBand("F32", BandArithmetic(Resample(CompositeBand("U16", B["02"], B["03"], B["08"]),5,"Bilinear Interpolation"), "40000000000*b1*b2/(b3*b3*b3*b3*b3*b3)"), BandArithmetic(Resample(CompositeBand("U16", B["06"], B["11"], B["12"]),5), "b1*b2*b2*b2*b3/100000000000")), "50000*b1/(b2*b2) -1"), None)

def TEST (B,X,fltthr):
  res8 = rasterItem(Resample(B["08"],5), id=1)
  return index(Local("U8", "Boolean And", 
    Local("U8", "Greater Than", BandArithmetic(CompositeBand("F32", Resample(B["04"],5), res8[0]), "95*b1 - 105*b2"), 0),
    Local("U8", "Greater Than", BandArithmetic(CompositeBand("F32", Resample(B["03"],5), res8[1]), "92*b1 - 108*b2"), 0)
  ), None)

