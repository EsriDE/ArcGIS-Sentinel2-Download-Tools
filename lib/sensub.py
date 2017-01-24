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

"""Common utilities & helper functions for Sentinel geoprocessing tools."""
VERSION=20170123
SCIHUB="https://scihub.copernicus.eu/"; DHUS=SCIHUB+"dhus/"; PRODUCTS=DHUS+"odata/v1/Products('%s')/"
CHECKSUM,SAFEZIP,SAFEROOT = PRODUCTS+"Checksum/Value/$value", PRODUCTS+"$value", PRODUCTS+"Nodes('%s.SAFE')/"
AWS="http://sentinel-s2-l1c.s3.amazonaws.com/"
AOIDEMO="7.58179313821144 51.93624645888022 7.642306784531163 51.968128265779484" # Münster.
PARTIAL=".partial"
ROWSSTEP=100 # Ultimate DHuS pagination page size limit (rows per page).
PSD13LEN=78 # Title length of a product that complies with PSD version < 14.
import os,urllib2,json,datetime,time,re
import xml.etree.cElementTree as ET
arcpy = THERE = None # Will be set by the importing module.

def auth (usr, pwd):
  """Globally install Basic Auth."""
  pm = urllib2.HTTPPasswordMgrWithDefaultRealm()
  pm.add_password(None, DHUS, usr, pwd)
  urllib2.install_opener(urllib2.build_opener(urllib2.HTTPBasicAuthHandler(pm)))

def sql (pythonSet):
  """Make a SQL string from a python set of UUIDs."""
  return re.sub("^set|[u \[\]]", "", str(pythonSet))

def search (sensingMin, sensingMax=None, aoiEnv=AOIDEMO, overlapMin=None, cloudyMax=None, rowsMax=ROWSSTEP):
  """Formulate & run a catalog query."""
  finds = dict()
  if rowsMax <=0: return finds
  url = DHUS + "search?format=xml&sortedby=beginposition&order=desc&rows=%d"%ROWSSTEP
  latest = "NOW" if sensingMax is None else sensingMax.isoformat()+"Z" # Z for Zulu, UTC.
  url += "&q=producttype:S2MSI1C+AND+beginPosition:[%s+TO+%s]" % (sensingMin.isoformat()+"Z", latest)
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
    rsp = urllib2.urlopen(url + str(offset))
    root=ET.ElementTree(file=rsp).getroot(); ns={"atom":"http://www.w3.org/2005/Atom", "opensearch":"http://a9.com/-/spec/opensearch/1.1/"}
    if offset==0: # First page:
      found = int(root.find("opensearch:totalResults",ns).text)
      txt = "Products found: %d" % found
      if found>rowsMax: txt += ", trimmed to (user wanted) %d"%rowsMax
      else: rowsBreak = found
      notify(txt)
    for e in root.iterfind("atom:entry",ns):
      if len(finds)>=rowsBreak: break
      sensingZulu = e.find("atom:date[@name='beginposition']",ns).text[:19] # With PSD version >=14, date string has millis appended.
      cloudy = float(e.find("atom:double[@name='cloudcoverpercentage']",ns).text)
      finds[e.find("atom:id",ns).text] = (e.find("atom:title",ns).text, datetime.datetime.strptime(sensingZulu, "%Y-%m-%dT%H:%M:%S"), cloudy, e.find("atom:str[@name='size']",ns).text)
    offset += ROWSSTEP
  return finds

def prodTiles (Title, UUID, Sensing, preview=True):
  """Resolve product's tile(s) image path(s)."""
  tiles = dict()
  try:
    url = "%sproducts/%d/%d/%d/%s/productInfo.json" % (AWS, Sensing.year,Sensing.month,Sensing.day, Title)
    info = json.load(urllib2.urlopen(url))
    imgName = "preview" if preview else "%s"
    for t in info["tiles"]: tiles["%d%s%s" % (t["utmZone"], t["latitudeBand"], t["gridSquare"])] = "%s/%s.jp2" % (t["path"], imgName)
    urlFormat = AWS+"%s"
  except urllib2.HTTPError as err:
    if err.code==404: # Why are some product paths not valid? For example: products/2016/7/20/S2A_OPER_PRD_MSIL1C_PDMC_20160805T152827_R051_V20160720T105547_20160720T105547/productInfo.json
      notify("%s: Missing product info on AWS, using DHuS as fallback..."%Title, 1)
      safeRoot = SAFEROOT%(UUID,Title)
      url = safeRoot + "Nodes('manifest.safe')/$value"
      info = urllib2.urlopen(url).read()
      GRANULE = r"GRANULE/[^/]+_T(\d{1,2}[A-Z]{3})_[^/]+/%s_DATA/[^.]+%s\.jp2"
      pat = GRANULE%("QI","") if preview else GRANULE%("IMG","_B01")
      for m in re.finditer(pat,info):
        path = m.group()
        if not preview: path = path.replace("_B01","_%s")
        tiles[m.group(1)] = re.sub("([^/]+)", r"Nodes('\1')", path)
      urlFormat = safeRoot + "%s/$value"
    else: raise
  return tiles,urlFormat


def md5sum (UUID):
  """Fetch MD5 hash for the product with given UUID."""
  return urllib2.urlopen(CHECKSUM%UUID).read()

KiB=1024; MiB=KiB**2
def download (url, folder=os.environ["TEMP"], filename=None, md5sum=None, unzip=False, unzipName=None, slim=False):
  """Download resource content to file in folder, where filename may implicitly be given by resource MIME header.
  Optionally check MD5 sum and/or unzip file content to folder (where appropriate)."""
  issue,severity = None,0
  folder = os.path.realpath(folder) # Paranoid.
  if not os.path.isdir(folder):
    issue="not a directory"; severity=notify("%s: %s!"%(folder, issue), 1)
    return filename,issue,severity
  rsp=None
  if not filename: # As a fallback, check MIME header:
    rsp = urllib2.urlopen(url)
    cd = rsp.headers.getheader("Content-Disposition")
    if cd:
      import cgi
      par = cgi.parse_header(cd)[1]
      fn=par.get("filename")
      if fn: filename=par["filename"]
  if not filename: filename="unknown" # Last resort.
  filename = os.path.basename(filename) # Paranoid.
  target = os.path.join(folder, filename)

  # Do not overwrite:
  toCheck=[target]
  if slim: tmp=target
  else:
    tmp=target+PARTIAL; toCheck.append(tmp)
  if unzip:
    unzipped = folder # Dummy so far.
    if unzipName is not None: unzipName = os.path.basename(unzipName).strip() # Paranoid.
    if unzipName:
      unzipped=os.path.join(folder,unzipName); toCheck.append(unzipped)
  for f in toCheck:
    if os.path.exists(f):
      issue="already exists"; severity=notify("%s: %s!"%(f, issue), 1)
  if issue: return target,issue,severity

  if not rsp: rsp=urllib2.urlopen(url)
  cl = rsp.headers.getheader("Content-Length")
  size = int(cl) if cl else -1
  if size>-1 and not slim: # Check free disk space:
    import ctypes
    free = ctypes.c_ulonglong()
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(folder), None, None, ctypes.pointer(free))
    estimated = size if not unzip else 2.5*size
    if free.value<estimated:
      issue="not enough space"; severity=notify("%s: %s, free is %d MiB but estimated need is %d MiB!"%(folder, issue, int(round(free.value/MiB)), int(round(estimated/MiB))), 1)
      return target,issue,severity

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

  if not issue:
    if not slim: os.rename(tmp,target)
    if unzip:
      import zipfile
      if zipfile.is_zipfile(target):
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
        target=unzipped
        if not pathTooLong: os.remove(z.filename)
        if unzipped.endswith(".SAFE"):
          hit = filter(re.compile("MTD_.+\.xml").search, os.listdir(unzipped)) #re.compile("S2.+_SAFL.+\.xml").match
          if hit:
            if hit[0].startswith("MTD"): # PSD14 not yet supported by ArcGIS(10.5) => workaround (sloppy):
              with open(os.path.join(target, "manifest.safe")) as f:
                tci = re.search(r"GRANULE/[^/]+/IMG_DATA/T[^.]+_TCI\.jp2", f.read())
                if tci: target=os.path.join(target, tci.group(0))
            else: target=os.path.join(unzipped, hit[0]) # The product's XML-based main definition.
      else:
        issue="not a zip file"; severity=notify("%s: %s!"%(tmp, issue), 2)
  return target,issue,severity


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
  if not folder: folder=os.path.join(THERE,"lyr")
  fullpath = os.path.join(folder, name)
  with open(fullpath): pass
  return fullpath

def recall (tool, params, exclusion=list()):
  """Pull parameter settings from process environment.
  Besides, populate tool's parameter map (name->index), providing 'parameter by name'."""
  for i,p in enumerate(params):
    if p.parameterType!="Derived" and p.name not in exclusion: p.value=os.getenv(p.name)
    tool.i[p.name]=i

def memorize (params):
  """Push parameter settings as presets into process environment.
  Becomes effective on a subsequent script execution when you have evoked a Refresh (F5) on the respective toolbox icon beforehand (from within ArcGIS Desktop)."""
  for p in params:
    if p.value is not None and p.parameterType!="Derived": os.environ[p.name]=p.valueAsText
    elif os.environ.has_key(p.name): del os.environ[p.name]

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
  """Validate GPDate very generally ."""
  # Is there any GPDate parameter option to enforce 'Date only' in advance, i.e. to disable 'Date and Time' and 'Time only'??
  # See also https://geonet.esri.com/thread/100190
  #   "Is there a way to limit the Date date type to Date only ie limit the Calendar date format radial buttons?"
  if param.value and param.valueAsText.find(":")>0:
    param.setWarningMessage("Please restrict to 'Date only'.")
    param.value = dayStart(param.value.date())

def prjExtent (tool, extent, name, origin):
  """Get projected extent (for designated named parameter) if originating extent is defined."""
  if not extent.spatialReference or extent.spatialReference.name=="Unknown": tool.w[name] = origin+": Unknown spatial reference, nothing copied over."
  else: return str(extent.projectAs(tool.WGS84))

