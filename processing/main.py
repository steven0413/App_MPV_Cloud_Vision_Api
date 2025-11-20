# Análisis imágenes + detección anomalías
import base64 # Para decodificar mensajes Pub/Sub
import json
import os
from google.cloud import storage, vision, firestore
import logging
import functions_framework 
from google.cloud import vision # Cloud Vision API


# Configuración
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'prj-botlabs-dev-aiasigna-images')
PROJECT_ID = os.environ.get('GCP_PROJECT', 'prj-botlabs-dev')

# Clientes GCP inicializados
storage_client = storage.Client() # Cloud Storage
vision_client = vision.ImageAnnotatorClient() # Cloud vision API
firestore_client = firestore.Client() # Firestore

# Clase para procesamiento de imágenes
class ImageProcessor:
    def __init__(self):
        self.authentic_products = self.load_authentic_references()
    
    # referencias de productos auténticos
    def load_authentic_references(self): 
        """Cargar referencias de productos auténticos"""
        return {
            "bayer": {
                "brand_name": "BAYER",
                "expected_colors": ["#FFFFFF", "#FF0000", "#0033A0"],  # Blanco, Rojo Bayer, Azul
                "expected_fonts": ["Arial", "Helvetica"], # Fuentes comunes usadas por Bayer
                "required_text": ["BAYER", "ASPIRINA", "REGISTRO", "SANITARIO", "LABORATORIO", "FABRICANTE"], # Texto clave esperado
                "expected_labels": ["medicine", "pharmacy", "medical", "drug", "pill", "tablet", "bottle"],# Etiquetas comunes relacionadas
                "security_features": ["Hologram", "QR Code", "Batch Number"],# Características de seguridad comunes
                "packaging_elements": ["Cross logo", "Bayer logo", "Pharmaceutical symbols"] # Elementos visuales comunes
            },
            "fla": {
                "brand_name": "FLA",
                "expected_colors": ["#8B0000", "#FFD700", "#000000", "#FFFFFF"],  # Rojo oscuro, Dorado, Negro, Blanco
                "expected_fonts": ["Times New Roman", "Georgia", "Serif"], # Fuentes usadaspor la fla
                "required_text": ["FLA", "RON", "EL CONSUMO DE ESTE PRODUCTO ES NOCIVO PARA LA SALUD", "CONTENIDO", "Aguardiente Antioqueño", "BOTELLA", "IMPORTADO"],
                "expected_labels": ["alcohol", "bottle", "wine", "beer", "liquor", "rum", "spirits"],
                "security_features": ["Tax Stamp", "Seal", "Hologram"],
                "packaging_elements": ["FLA logo", "Rum bottle", "Caribbean symbols"]
            }
        }

    def process_image(self, image_path, product_type=None):  # product_type ahora es opcional
        """Procesar imagen y detectar anomalías"""
        try:
            # 1. Descargar imagen de Cloud Storage
            image_content = self.download_image(image_path)
            
            # 2. Analizar con Cloud Vision API
            vision_analysis = self.analyze_with_vision_api(image_content)
            
            # 3. Detectar tipo de producto automáticamente si no se especifica
            if product_type is None:
                product_type = self.detect_product_type(vision_analysis)
                logging.info(f"Tipo de producto detectado: {product_type}")
            
            # 4. Detección de anomalías vs referencias específicas
            anomalies = self.detect_anomalies(vision_analysis, product_type)
            
            # 5. Calcular probabilidad de falsificación
            probability = self.calculate_counterfeit_probability(anomalies, vision_analysis, product_type)
            
            return {
                'probability': probability,
                'anomalies': anomalies,
                'product_type': product_type,
                'brand': self.authentic_products[product_type]['brand_name'],
                'vision_analysis': {
                    'text_found': len(vision_analysis['text_annotations']) > 0,
                    'labels_found': [label['description'] for label in vision_analysis['labels'][:5]],
                    'dominant_colors': [self.rgb_to_hex(color['color']) for color in vision_analysis['colors'][:3]]
                },
                'status': 'completed'
            }
            
        except Exception as e:
            logging.error(f"Error procesando imagen: {e}")
            raise

    # detección automática de tipo de producto   
    def detect_product_type(self, vision_analysis):
        """Detectar automáticamente si es Bayer o FLA basado en texto y etiquetas"""
        detected_text = ' '.join([t['description'].upper() for t in vision_analysis['text_annotations']])
        detected_labels = [label['description'].lower() for label in vision_analysis['labels']]
        
        # Puntaje para cada marca
        bayer_score = 0
        fla_score = 0
        
        # Verificar texto específico de Bayer
        bayer_keywords = ["BAYER", "ASPIRINA", "MEDICAMENTO", "FARMACIA", "LABORATORIO"]
        for keyword in bayer_keywords:
            if keyword in detected_text:
                bayer_score += 2
        
        # Verificar texto específico de FLA
        fla_keywords = ["FLA", "RON", "LICOR", "ALCOHOL", "BOTELLA", "DISTRIBUIDOR"]
        for keyword in fla_keywords:
            if keyword in detected_text:
                fla_score += 2
        
        # Verificar etiquetas de Vision API
        bayer_labels = ["medicine", "pharmacy", "medical", "drug", "pill", "tablet"]
        fla_labels = ["alcohol", "bottle", "wine", "beer", "liquor", "rum"]
        
        for label in detected_labels:
            if any(bayer_label in label for bayer_label in bayer_labels):
                bayer_score += 1
            if any(fla_label in label for fla_label in fla_labels):
                fla_score += 1
        
        logging.info(f"Puntajes - Bayer: {bayer_score}, FLA: {fla_score}")
        
        # Determinar tipo de producto
        if bayer_score > fla_score and bayer_score >= 2:
            return "bayer"
        elif fla_score > bayer_score and fla_score >= 2:
            return "fla"
        else:
            logging.warning("No se pudo determinar el tipo de producto, usando Bayer por defecto")
            return "bayer"     

    # descargar imagen de Cloud Storage
    def download_image(self, gcs_path):
        """Descargar imagen de Cloud Storage"""
        # gs://bucket-name/path/to/image.jpg
        bucket_name = gcs_path.split('/')[2]
        blob_name = '/'.join(gcs_path.split('/')[3:])
        
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()
    
    # análisis con vision API - llamadas paralelas a visión api OCR, labels, colors
    def analyze_with_vision_api(self, image_content):
        """Analizar imagen con Google Vision API"""
        image = vision.Image(content=image_content)
        
        # 1. OCR - detección de texto
        text_response = vision_client.text_detection(image=image)
        # 2. label detection - identificación de objetos
        label_response = vision_client.label_detection(image=image)
         # 3. image properties - colors dominantes
        color_response = vision_client.image_properties(image=image)
        
        return {
            'text_annotations': [
                {
                    'description': annotation.description,
                    'confidence': getattr(annotation, 'confidence', 0.0)
                }
                for annotation in text_response.text_annotations
            ],
            'labels': [
                {
                    'description': label.description,
                    'score': label.score
                }
                for label in label_response.label_annotations
            ],
            'colors': [
                {
                    'color': {
                        'red': color.color.red,
                        'green': color.color.green,
                        'blue': color.color.blue
                    },
                    'score': color.score,
                    'pixel_fraction': color.pixel_fraction
                }
                for color in color_response.image_properties_annotation.dominant_colors.colors
            ]
        }
    
    # detección de anomalías
    def detect_anomalies(self, vision_analysis, product_type):
        """✅ DETECCIÓN MEJORADA DE ANOMALÍAS"""
        anomalies = []
        reference = self.authentic_products[product_type]
        
        # Verificar texto requerido
        detected_text = ' '.join([t['description'].upper() for t in vision_analysis['text_annotations']])
        text_anomalies = self.check_text_anomalies(detected_text, reference['required_text'])
        anomalies.extend(text_anomalies)
        
        # Verificar colors 
        detected_colors = [c['color'] for c in vision_analysis['colors'][:5]]
        color_anomalies = self.check_color_anomalies(detected_colors, reference['expected_colors'])
        anomalies.extend(color_anomalies)
        
        # Verificar etiquetas
        label_anomalies = self.check_label_anomalies(vision_analysis['labels'], reference['expected_labels'])
        anomalies.extend(label_anomalies)
        
        # Verificar calidad de imagen
        if len(vision_analysis['text_annotations']) < 2:
            anomalies.append("Texto en etiqueta poco claro o ilegible")
        
        return anomalies
    
    # verificación de texto requerido MLheurística
    def check_text_anomalies(self, detected_text, required_texts):
        """ Verificar texto requerido"""
        anomalies = []
        for required in required_texts:
            if required not in detected_text:
                anomalies.append(f"Texto requerido no encontrado: '{required}'")
        return anomalies
    
    # verificación de colores
    def check_color_anomalies(self, detected_colors, expected_colors_hex):
        """ VERIFICACIÓN MEJORADA DE COLORES"""
        anomalies = []
        
        if not detected_colors:
            anomalies.append("No se pudieron detectar colores en la imagen")
            return anomalies
        
        # Convertir colores detectados a HEX
        detected_hex = [self.rgb_to_hex(color) for color in detected_colors[:3]] # Usar solo los 3 colores dominantes
        
        # Verificar similitud con colores esperados
        color_matches = 0
        for expected_hex in expected_colors_hex:
            for detected_hex_color in detected_hex:
                if self.color_similarity(expected_hex, detected_hex_color) > 0.7: # umbral de similitud
                    color_matches += 1
                    break
        
        if color_matches < 1:
            anomalies.append("Inconsistencias significativas en colores de etiqueta")
        elif color_matches < 2:
            anomalies.append("Ligeras inconsistencias en colores de etiqueta")
            
        return anomalies
    
    # verificación de etiquetas
    def check_label_anomalies(self, detected_labels, expected_labels):
        """ Verificar etiquetas esperadas"""
        anomalies = []
        detected_label_descriptions = [label['description'].lower() for label in detected_labels]
        
        expected_found = sum(1 for expected in expected_labels 
                           if any(expected in detected for detected in detected_label_descriptions))
        
        if expected_found == 0:
            anomalies.append("No se detectaron características esperadas del producto")
        elif expected_found <= 1:
            anomalies.append("Pocas características del producto detectadas")
            
        return anomalies
    
    # convertir RGB a Hexadecimal
    def rgb_to_hex(self, color):
        """Convertir RGB a HEX"""
        r = int(color['red'] * 255)
        g = int(color['green'] * 255) 
        b = int(color['blue'] * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    # calcular similitud entre colores
    def color_similarity(self, hex1, hex2):
        """✅ CALCULAR SIMILITUD ENTRE COLORES HEX"""
        # Convertir HEX a RGB
        r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16) # RGB del color 1
        r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16) # RGB del color 2
        
        # Calcular distancia euclidiana
        distance = ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5
        max_distance = (255 ** 2 * 3) ** 0.5 # Distancia máxima posible
        
        # Convertir a similitud (1 = idéntico, 0 = completamente diferente)
        similarity = 1 - (distance / max_distance)
        return similarity
    
    # cálculo de probabilidad de falsificación     
    def calculate_counterfeit_probability(self, anomalies, vision_analysis, product_type):
        """✅ ALGORITMO DE PROBABILIDAD"""
        base_probability = 10  # Probabilidad base
        
        # Pesos dinámicos basados en la importancia para cada producto
        weights = {
            "bayer": {
                'texto_no_encontrado': 30,      # Crítico en medicamentos
                'inconsistencias_significativas_colores': 25,
                'inconsistencias_leves_colores': 15,
                'no_caracteristicas_esperadas': 40,  #  importante
                'pocas_caracteristicas': 20,
                'texto_ilegible': 35,           #  importante
                'falta_sello_seguridad': 50     
            },
            "fla": {
                'texto_no_encontrado': 20,
                'inconsistencias_significativas_colores': 35,  #  importante en licores
                'inconsistencias_leves_colores': 20,
                'no_caracteristicas_esperadas': 25,
                'pocas_caracteristicas': 15,
                'texto_ilegible': 20,
                'falta_sello_seguridad': 30    
            }
        }    

        product_weights = weights[product_type]
        total_increase = 0
        
        # Evaluar cada anomalía y sumar su peso
        for anomaly in anomalies:
            if "Texto requerido no encontrado" in anomaly:
                total_increase += product_weights['texto_no_encontrado']
            elif "Inconsistencias significativas" in anomaly:
                total_increase += product_weights['inconsistencias_significativas_colores']
            elif "Ligeras inconsistencias" in anomaly:
                total_increase += product_weights['inconsistencias_leves_colores']
            elif "No se detectaron características" in anomaly:
                total_increase += product_weights['no_caracteristicas_esperadas']
            elif "Pocas características" in anomaly:
                total_increase += product_weights['pocas_caracteristicas']
            elif "Texto en etiqueta poco claro" in anomaly:
                total_increase += product_weights['texto_ilegible']
            elif "Sello de seguridad" in anomaly:
                total_increase += product_weights['falta_sello_seguridad']
            else:
                total_increase += 8 # Peso por anomalías menores
        
        # Factores de ajuste basados en calidad de análisis
        quality_adjustment = 0

        # Penalizar si no se detectó texto - prudto con texto poco claro
        if not vision_analysis['text_annotations']:
            quality_adjustment += 15
        
        # Bonificar si se detectan múltiples características esperadas
        expected_labels = self.authentic_products[product_type]['expected_labels']
        detected_labels = [label['description'].lower() for label in vision_analysis['labels']]
        matches = sum(1 for expected in expected_labels if any(expected in detected for detected in detected_labels)) # 
        
        if matches >= 3:  # Si coincide con 3+ características, reducir probabilidad
            quality_adjustment -= 10
        
        total_probability = min(base_probability + total_increase + quality_adjustment, 95) # Máximo 95% evitar falsos positivos extremos.
        return max(5, total_probability)  # Mínimo 5% de probabilidad evitar dar certeza absoluta de autenticidad

# Manejador de Cloud Functions para Pub/Sub
@functions_framework.cloud_event
def process_image_pubsub(cloud_event):
    """Manejador de Pub/Sub para procesamiento de imágenes"""
    try:
        # Decodificar mensaje de Pub/Sub
        message_data = json.loads(base64.b64decode(cloud_event.data['message']['data']).decode('utf-8'))
        
        logging.info(f"Iniciando procesamiento para usuario: {message_data['user_id']}")
        
        processor = ImageProcessor()
        
        
        result = processor.process_image(
            image_path=message_data['image_path'],
            product_type=None # Detectar automáticamente el tipo de producto
        )
        
        # Guardar resultado en Firestore
        save_to_firestore(message_data['user_id'], message_data['message_id'], result)
        
        logging.info(f"Procesamiento completado para {message_data['user_id']}: {result['probability']}%")
        
    except Exception as e:
        logging.error(f"Error en process_image_pubsub: {e}")
        raise

def save_to_firestore(user_id, message_id, result):
    """Guardar resultados en Firestore"""
    doc_ref = firestore_client.collection('analysis_results').document()
    doc_ref.set({
        'user_id': user_id,
        'message_id': message_id,
        'timestamp': firestore.SERVER_TIMESTAMP,
        'probability': result['probability'],
        'anomalies': result['anomalies'],
        'analysis_data': result.get('vision_analysis', {}),
        'status': 'completed'
    })
    
    logging.info(f"Resultados guardados en Firestore para {user_id}")