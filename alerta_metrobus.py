import os
import logging
import requests
import zipfile
import io
import csv
import math
import datetime
from bs4 import BeautifulSoup
from google.transit import gtfs_realtime_pb2

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
USUARIO = os.getenv("USUARIO_API_KEY")
SENHA = os.getenv("SENHA_API_KEY")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class MetrobusMonitor:
    def __init__(self, url_semovi: str):
        self.url_semovi = url_semovi

    @staticmethod
    def calcular_distancia(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    # ==================== METROBÚS ====================
    def obtener_estado_oficial(self) -> str:
        """Estado oficial del Metrobús + detección de manifestaciones"""
        if not SCRAPER_API_KEY:
            return "Error: Falta la clave de ScraperAPI."

        problemas = []
        try:
            parametros_proxy = {
                'api_key': SCRAPER_API_KEY,
                'url': self.url_semovi,
                'country_code': 'mx'
            }

            respuesta = requests.get('http://api.scraperapi.com/', params=parametros_proxy, timeout=60)
            respuesta.raise_for_status()

            soup = BeautifulSoup(respuesta.text, 'html.parser')
            tablas = soup.find_all('table')

            mapeo_lineas = {
                1: "Línea 1", 2: "Línea 2", 3: "Línea 3",
                4: "Línea 4", 5: "Línea 5", 6: "Línea 6",
                7: "Línea 7", 8: "Línea 8"
            }

            palabras_manifestacion = ["manifestación", "manifestacion", "protesta", "bloqueo", "marcha", "plantón"]

            for tabla in tablas:
                if 'estaciones afectadas' in tabla.text.lower():
                    for num_fila, fila in enumerate(tabla.find_all('tr')[1:], start=1):
                        celdas = fila.find_all('td')
                        if len(celdas) >= 3:
                            linea_nombre = mapeo_lineas.get(num_fila, f"Línea {num_fila}")
                            est = celdas[1].get_text(strip=True)
                            afec = celdas[2].get_text(strip=True)
                            info_adicional = celdas[3].get_text(strip=True) if len(celdas) >= 4 else ""

                            texto_completo = f"{est} {afec} {info_adicional}".lower()
                            est_limpio = est.lower().replace("estado", "").strip()

                            if "servicio regular" not in est_limpio:
                                es_manifestacion = any(p in texto_completo for p in palabras_manifestacion)
                                tipo = "🚫 Cerrada por manifestación" if es_manifestacion else "⚠️ Cerrada"

                                reporte = f"- {linea_nombre}: {tipo}\n  Estaciones: {afec}"
                                if info_adicional and info_adicional.lower() not in ["ninguna", ""]:
                                    reporte += f"\n  Info: {info_adicional}"
                                problemas.append(reporte)

            return "✅ Metrobús: Servicio regular." if not problemas else "🚨 METROBÚS - AFECTACIONES:\n\n" + "\n\n".join(problemas)

        except Exception as e:
            return f"Error en Metrobús: {str(e)}"

    # ==================== METRO CDMX ====================
    def obtener_estado_metro(self) -> str:
        """Estado del Metro (todas las líneas) + detección de motivo"""
        if not SCRAPER_API_KEY:
            return ""

        try:
            url_metro = "https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml?idMedioTransporte=metro"

            parametros_proxy = {
                'api_key': SCRAPER_API_KEY,
                'url': url_metro,
                'country_code': 'mx'
            }

            respuesta = requests.get('http://api.scraperapi.com/', params=parametros_proxy, timeout=60)
            respuesta.raise_for_status()

            soup = BeautifulSoup(respuesta.text, 'html.parser')
            tablas = soup.find_all('table')

            lineas_afectadas = []
            linea_12_afectada = False

            palabras_manifestacion = ["manifestación", "manifestacion", "protesta", "bloqueo", "marcha", "plantón"]
            palabras_mantenimiento = ["mantenimiento", "rehabilitación", "obra", "falla técnica", "técnico"]

            for tabla in tablas:
                for fila in tabla.find_all('tr')[1:]:
                    celdas = fila.find_all('td')
                    if len(celdas) >= 3:
                        linea = celdas[0].get_text(strip=True)
                        estado = celdas[1].get_text(strip=True).lower()
                        estaciones = celdas[2].get_text(strip=True)
                        info_adicional = celdas[3].get_text(strip=True) if len(celdas) >= 4 else ""

                        if "servicio regular" not in estado:
                            texto_completo = f"{estado} {estaciones} {info_adicional}".lower()

                            if any(p in texto_completo for p in palabras_manifestacion):
                                motivo = "🚫 Manifestación / Bloqueo"
                            elif any(p in texto_completo for p in palabras_mantenimiento):
                                motivo = "🔧 Mantenimiento / Obra"
                            else:
                                motivo = "⚠️ Otro motivo"

                            info_linea = f"- {linea}: {motivo}\n  Estaciones: {estaciones}"
                            if info_adicional and info_adicional.lower() not in ["ninguna", ""]:
                                info_linea += f"\n  Detalle: {info_adicional}"

                            lineas_afectadas.append(info_linea)

                            if "12" in linea:
                                linea_12_afectada = True

            if not lineas_afectadas:
                return "✅ Metro CDMX: Servicio regular en todas las líneas."

            header = "🚇 METRO CDMX - AFECTACIONES:\n"
            if linea_12_afectada:
                header += "\n⚠️ **Línea 12 (Dorada) está afectada**\n"

            return header + "\n\n".join(lineas_afectadas)

        except Exception as e:
            logging.error(f"Error Metro: {str(e)}")
            return ""

    # ==================== GTFS METROBÚS (COMPLETO) ====================
    def procesar_datos_gtfs(self) -> tuple:
        """Asistente Personal + Termómetro + Hotspots (versión completa)"""
        reporte_asistente = ""
        reporte_termometro = ""
        reporte_hotspots = ""

        if not USUARIO or not SENHA:
            return "", "", ""

        try:
            url_auth = "https://metrobus-gtfs.sinopticoplus.com/gtfs-api/partnerValidation"
            credenciales = {"usuario": USUARIO, "senha": SENHA}

            auth_res = requests.post(url_auth, json=credenciales, timeout=15)
            auth_res.raise_for_status()
            urls = auth_res.json()

            zip_res = requests.get(urls['urlStatic'], timeout=30)
            zip_res.raise_for_status()

            mapa_rutas = {}
            mapa_paradas = []

            with zipfile.ZipFile(io.BytesIO(zip_res.content)) as z:
                with z.open('routes.txt') as f:
                    for fila in csv.DictReader(io.TextIOWrapper(f, 'utf-8')):
                        nombre_corto = fila.get('route_short_name', '').strip()
                        mapa_rutas[fila['route_id']] = f"Línea {nombre_corto}" if nombre_corto else ""

                with z.open('stops.txt') as f:
                    for fila in csv.DictReader(io.TextIOWrapper(f, 'utf-8')):
                        mapa_paradas.append({
                            'nombre': fila.get('stop_name', 'Estación Desconocida'),
                            'lat': float(fila['stop_lat']),
                            'lon': float(fila['stop_lon'])
                        })

            rt_res = requests.get(urls['urlRealTime'], timeout=30)
            rt_res.raise_for_status()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(rt_res.content)

            hora_cdmx = (datetime.datetime.utcnow() - datetime.timedelta(hours=6)).hour
            es_manana = hora_cdmx < 12

            if es_manana:
                estacion, destino = "Félix Cuevas", "Villa Olímpica"
                lat_origen, lon_origen = 19.3725, -99.1798
            else:
                estacion, destino = "Villa Olímpica", "Félix Cuevas"
                lat_origen, lon_origen = 19.3648, -99.1835

            buses_utiles = []
            buses_por_ruta = {}

            for entidad in feed.entity:
                if entidad.vehicle.HasField("trip") and entidad.vehicle.HasField("position"):
                    r_id = entidad.vehicle.trip.route_id
                    nombre_linea = mapa_rutas.get(r_id, "")
                    if not nombre_linea:
                        continue

                    velocidad_kmh = entidad.vehicle.position.speed * 3.6

                    if nombre_linea not in buses_por_ruta:
                        buses_por_ruta[nombre_linea] = []

                    bus_data = {
                        'id': entidad.vehicle.vehicle.id if entidad.vehicle.HasField("vehicle") else str(entidad.id),
                        'lat': entidad.vehicle.position.latitude,
                        'lon': entidad.vehicle.position.longitude,
                        'speed': velocidad_kmh
                    }
                    buses_por_ruta[nombre_linea].append(bus_data)

                    if nombre_linea == "Línea 1":
                        lat_bus = bus_data['lat']
                        lon_bus = bus_data['lon']
                        bearing = entidad.vehicle.position.bearing
                        distancia = self.calcular_distancia(lat_origen, lon_origen, lat_bus, lon_bus)

                        if es_manana:
                            if distancia <= 1.5:
                                buses_utiles.append(distancia)
                        else:
                            va_al_norte = (bearing < 90 or bearing > 270)
                            esta_al_sur = lat_bus < lat_origen
                            if va_al_norte and esta_al_sur and distancia <= 6.0:
                                buses_utiles.append(distancia)

            buses_utiles.sort()

            # === ASISTENTE PERSONAL ===
            titulo_asis = f"🎯 ASISTENTE PERSONAL (GPS)\n_Tu viaje: {estacion} ➔ {destino}_\n"

            if es_manana:
                cantidad = len(buses_utiles)
                if cantidad >= 4:
                    estado = "🟢 Excelente (Línea fluyendo)"
                elif cantidad >= 2:
                    estado = "🟡 Normal"
                else:
                    estado = "🔴 Baja disponibilidad (Posible retraso)"
                reporte_asistente = titulo_asis + f"Terminal: {estado} ({cantidad} unidades listas)."
            else:
                if not buses_utiles:
                    reporte_asistente = titulo_asis + "⚠️ No hay unidades acercándose en 6km. Fuerte retraso."
                else:
                    el_proximo = buses_utiles[0]
                    tiempo_min = max(1, int(el_proximo * 3.75))
                    reporte_asistente = titulo_asis + (
                        f"🚌 Próximo Metrobús: A {el_proximo:.1f} km.\n"
                        f"⏱️ Llegada estimada: ~{tiempo_min} minutos.\n"
                        f"📊 Vienen {len(buses_utiles)} unidades más en camino."
                    )

            # === TERMÓMETRO ===
            buses_l1 = buses_por_ruta.get("Línea 1", [])
            if buses_l1:
                avg_speed = sum(b['speed'] for b in buses_l1) / len(buses_l1)
                if avg_speed >= 14.0:
                    estado_term = "🟢 Fluido"
                elif avg_speed >= 10.0:
                    estado_term = "🟡 Moderado"
                else:
                    estado_term = "🔴 Tráfico Pesado"
                reporte_termometro = f"🌡️ TERMÓMETRO DE RUTA\n- Línea 1: {estado_term} (Vel. promedio: {avg_speed:.1f} km/h)"

            # === HOTSPOTS (COMPLETO) ===
            terminales_ignoradas = [
                "indios verdes", "caminero", "gálvez", "colonia del valle",
                "tepalcates", "tacubaya", "etiopía", "tenayuca", "santa cruz atoyac",
                "balderas", "buenavista", "san lázaro", "pantitlán", "alameda oriente",
                "remedios", "preparatoria 1", "rosario", "villa de aragón",
                "hospital infantil", "campo marte"
            ]

            hotspots_msg = []
            buses_procesados = set()

            for i, bus_origen in enumerate(buses_l1):
                if bus_origen['id'] in buses_procesados:
                    continue

                cluster = [bus_origen]
                for j, bus_destino in enumerate(buses_l1):
                    if i == j or bus_destino['id'] in buses_procesados:
                        continue
                    dist = self.calcular_distancia(bus_origen['lat'], bus_origen['lon'],
                                                   bus_destino['lat'], bus_destino['lon'])
                    if dist <= 0.4:
                        cluster.append(bus_destino)

                if len(cluster) >= 4:
                    avg_speed = sum(b['speed'] for b in cluster) / len(cluster)
                    if avg_speed < 12.0:
                        centro_lat = sum(b['lat'] for b in cluster) / len(cluster)
                        centro_lon = sum(b['lon'] for b in cluster) / len(cluster)

                        estacion_cercana = "Desconocida"
                        min_dist = 999.0
                        for parada in mapa_paradas:
                            d = self.calcular_distancia(centro_lat, centro_lon, parada['lat'], parada['lon'])
                            if d < min_dist:
                                min_dist = d
                                estacion_cercana = parada['nombre']

                        es_terminal = any(t in estacion_cercana.lower() for t in terminales_ignoradas)
                        if not es_terminal:
                            hotspots_msg.append(
                                f"- 🚨 Fuerte aglomeración ({len(cluster)} unidades) cerca de {estacion_cercana}. "
                                f"Velocidad: {avg_speed:.1f} km/h."
                            )
                            for b in cluster:
                                buses_procesados.add(b['id'])

            if hotspots_msg:
                reporte_hotspots = "⚠️ ALERTAS DE TRÁFICO EN VIVO (Hotspots Línea 1)\n" + "\n".join(hotspots_msg)

            return reporte_asistente, reporte_termometro, reporte_hotspots

        except Exception as e:
            logging.error(f"Error en GTFS: {str(e)}")
            return "", "", ""

    def enviar_reporte_completo(self):
        reporte_metrobus = self.obtener_estado_oficial()
        reporte_metro = self.obtener_estado_metro()
        reporte_asistente, reporte_termometro, reporte_hotspots = self.procesar_datos_gtfs()

        # Construir mensaje final
        mensaje_final = reporte_metrobus

        if reporte_metro:
            mensaje_final += f"\n\n{reporte_metro}"

        if reporte_asistente:
            mensaje_final += f"\n\n{reporte_asistente}"
        if reporte_termometro:
            mensaje_final += f"\n\n{reporte_termometro}"
        if reporte_hotspots:
            mensaje_final += f"\n\n{reporte_hotspots}"

        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            logging.error("Faltan credenciales de Telegram.")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"🚇 REPORTE METROBÚS + METRO CDMX\n\n{mensaje_final}"
        }

        try:
            requests.post(url, json=payload, timeout=15).raise_for_status()
            logging.info("✅ Reporte enviado correctamente a Telegram")
        except Exception as e:
            logging.error(f"Error al enviar Telegram: {str(e)}")


if __name__ == "__main__":
    url_directa = "https://incidentesmovilidad.cdmx.gob.mx/public/bandejaEstadoServicio.xhtml?idMedioTransporte=mb"
    monitor = MetrobusMonitor(url_directa)
    monitor.enviar_reporte_completo()
