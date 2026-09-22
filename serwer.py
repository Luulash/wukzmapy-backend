import http.server
import json
import urllib.parse
import urllib.request
import math
import os


def wgs84_to_puwg92(lat, lng):
    L0 = 19.0 * math.pi / 180.0
    m0 = 0.9993
    x0 = 500000.0
    y0 = -5300000.0
    a = 6378137.0
    e_sq = 0.00669438002290

    fi = lat * math.pi / 180.0
    lambda_val = lng * math.pi / 180.0
    N = a / math.sqrt(1 - e_sq * math.sin(fi) ** 2)
    t = math.tan(fi)
    eta_sq = (e_sq / (1 - e_sq)) * math.cos(fi) ** 2
    l = lambda_val - L0

    A0 = 1 - (e_sq / 4) - (3 * e_sq ** 2 / 64) - (5 * e_sq ** 3 / 256)
    A2 = (3 / 8) * (e_sq + (e_sq ** 2 / 4) + (15 * e_sq ** 3 / 128))
    A4 = (15 / 256) * (e_sq ** 2 + (3 * e_sq ** 3 / 4))
    A6 = (35 * e_sq ** 3 / 3072)
    S = a * (A0 * fi - A2 * math.sin(2 * fi) + A4 * math.sin(4 * fi) - A6 * math.sin(6 * fi))

    x92 = m0 * (N * math.cos(fi) * l + (N / 6) * math.cos(fi) ** 3 * (1 - t ** 2 + eta_sq) * l ** 3 + (
                N / 120) * math.cos(fi) ** 5 * (
                            5 - 18 * t ** 2 + t ** 4 + 14 * eta_sq - 58 * eta_sq * t ** 2) * l ** 5) + x0
    y92 = m0 * (S + (N / 2) * math.sin(fi) * math.cos(fi) * l ** 2 + (N / 24) * math.sin(fi) * math.cos(fi) ** 3 * (
                5 - t ** 2 + 9 * eta_sq + 4 * eta_sq ** 2) * l ** 4 + (N / 720) * math.sin(fi) * math.cos(fi) ** 5 * (
                            61 - 58 * t ** 2 + t ** 4 + 270 * eta_sq - 330 * eta_sq * t ** 2) * l ** 6) + y0
    return round(x92, 2), round(y92, 2)


def get_nadlesnictwo_address(target_name):
    if not target_name:
        return ""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    txt_path = os.path.join(script_dir, 'nadlesnictwo.txt')
    if not os.path.exists(txt_path):
        txt_path = 'nadlesnictwo.txt'

    if not os.path.exists(txt_path):
        print("Brak pliku nadlesnictwo.txt w folderze:", script_dir)
        return ""

    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(';')
                if len(parts) >= 3:
                    name = parts[0].strip()
                    if name.lower() == target_name.strip().lower():
                        street = parts[1].strip()
                        city_code = parts[2].strip()
                        return f"{street}, {city_code}"
    except Exception as e:
        print("Błąd odczytu nadlesnictwo.txt:", e)
    return ""


class GeoHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == '/api/check':
            query_params = urllib.parse.parse_qs(parsed_url.query)
            try:
                lat = float(query_params['lat'][0])
                lng = float(query_params['lng'][0])

                x92, y92 = wgs84_to_puwg92(lat, lng)

                # 1. GUGiK - Pobranie ID oraz geometrii WKT w WGS84
                uldk_url = f"https://uldk.gugik.gov.pl/?request=GetParcelByXY&xy={x92},{y92}&result=id,geom_wkt&srid=4326"
                req = urllib.request.urlopen(uldk_url)
                uldk_text = req.read().decode('utf-8')

                parcel_id = None
                wkt_geom = None
                for line in uldk_text.split('\n'):
                    line = line.strip()
                    if not line or line == '0' or line.startswith('-'):
                        continue
                    if '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 2:
                            parcel_id = parts[0].strip()
                            wkt_geom = parts[1].strip()
                            break

                forest_info = ""
                if parcel_id:
                    # 2. BDL ArcGIS Identify
                    ext = 0.001
                    map_extent = f"{lng - ext},{lat - ext},{lng + ext},{lat + ext}"
                    bdl_url = f"https://mapserver.bdl.lasy.gov.pl/arcgis/rest/services/WMS_BDL/MapServer/identify?f=json&tolerance=5&returnGeometry=false&imageDisplay=800,600,96&geometry={lng},{lat}&geometryType=esriGeometryPoint&sr=4326&mapExtent={map_extent}&layers=all"

                    try:
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        req_bdl = urllib.request.Request(bdl_url, headers=headers)
                        with urllib.request.urlopen(req_bdl) as response:
                            bdl_data = json.loads(response.read().decode('utf-8'))
                            nadlesnictwo = ""
                            compartment_cd = ""

                            if 'results' in bdl_data:
                                for res in bdl_data['results']:
                                    layer_name = res.get('layerName', '')
                                    attrs = res.get('attributes', {})

                                    if 'nadleśnictwa' in layer_name.lower() or 'nadlesnictwa' in layer_name.lower():
                                        if 'inspectorate_name' in attrs:
                                            val = str(attrs['inspectorate_name']).strip()
                                            if val and val.lower() != 'null':
                                                nadlesnictwo = val

                                    if 'oddziały' in layer_name.lower() or 'oddzialy' in layer_name.lower():
                                        if 'compartment_cd' in attrs:
                                            val = str(attrs['compartment_cd']).strip()
                                            if val and val.lower() != 'null':
                                                compartment_cd = val

                                if not nadlesnictwo:
                                    for res in bdl_data.get('results', []):
                                        attrs = res.get('attributes', {})
                                        if 'inspectorate_name' in attrs:
                                            val = str(attrs['inspectorate_name']).strip()
                                            if val and val.lower() != 'null':
                                                nadlesnictwo = val
                                                break

                                if not compartment_cd:
                                    for res in bdl_data.get('results', []):
                                        attrs = res.get('attributes', {})
                                        if 'compartment_cd' in attrs:
                                            val = str(attrs['compartment_cd']).strip()
                                            if val and val.lower() != 'null':
                                                compartment_cd = val
                                                break

                                if compartment_cd or nadlesnictwo:
                                    if not nadlesnictwo: nadlesnictwo = "Nadleśnictwo"
                                    if not compartment_cd: compartment_cd = "Brak"

                                    # Pobranie adresu nadleśnictwa z pliku nadlesnictwo.txt
                                    nadl_address = get_nadlesnictwo_address(nadlesnictwo)

                                    if nadl_address:
                                        forest_info = f"; {compartment_cd}, {nadlesnictwo}, {nadl_address}"
                                    else:
                                        forest_info = f"; {compartment_cd}, {nadlesnictwo}"
                    except Exception as e:
                        print("Błąd BDL:", e)

                response_data = {
                    "parcelId": parcel_id,
                    "wkt": wkt_geom,
                    "forestSuffix": forest_info
                }

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(ex).encode('utf-8'))
        else:
            super().do_GET()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    server_address = ('0.0.0.0', port)
    httpd = http.server.HTTPServer(server_address, GeoHandler)
    print(f"Serwer uruchomiony na porcie {port}")
    httpd.serve_forever()
