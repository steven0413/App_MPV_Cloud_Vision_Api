import functions_framework # Web Framework de Google Cloud Functions
from flask import jsonify, request
from google.cloud import storage, pubsub_v1
import json
import os
import logging
import requests  # Para llamadas HTTP API whatsApp

# Configuración variables de entorno
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'prj-botlabs-dev-aiasigna-images')
TOPIC_NAME = os.environ.get('TOPIC_NAME', 'aiasigna-image-processing')
WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN', 'aiasigna_verify_123')
WHATSAPP_ACCESS_TOKEN = os.environ.get('WHATSAPP_ACCESS_TOKEN')  
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID') 

# Clientes GCP
storage_client = storage.Client()
publisher = pubsub_v1.PublisherClient()

# funcion principal Webhook de WhatsApp Business API
@functions_framework.http
def whatsapp_webhook(request):
    """Webhook para recibir mensajes de WhatsApp"""
    
    # Verificar token de WhatsApp GET → obtener datos y POST → crear recursos.
    if request.method == 'GET':
        return verify_webhook(request) # Verificación del webhook inicial de WhatsApp
    
    # Procesar mensaje entrante
    if request.method == 'POST':
        return process_message(request) # Procesar mensaje entrante
    
    return jsonify({'error': 'Método no permitido'}), 405

# Verificación del webhook
def verify_webhook(request):
    """Verificación del webhook para WhatsApp Business API"""
    mode = request.args.get('hub.mode') # Modo de verificación
    token = request.args.get('hub.verify_token') # Token de verificación configurado
    challenge = request.args.get('hub.challenge') 
    
    if mode == 'subscribe' and token == WHATSAPP_TOKEN:
        logging.info("Webhook verificado exitosamente")
        return challenge, 200 # Responder con el desafío para verificar el webhook
    
    logging.warning(f"Verificación fallida: mode={mode}, token={token}")
    return 'Verificación fallida', 403 # Responder con error si la verificación falla

# Procesar mensaje entrante
def process_message(request):
    """Procesar mensajes entrantes de WhatsApp"""
    try:
        data = request.get_json()
        logging.info(f"Mensaje recibido: {json.dumps(data, indent=2)}")
        
        # Extraer información del mensaje
        message_data = extract_message_data(data)
        
        if message_data.get('has_media'):
            # Procesar imagen
            return process_image_message(message_data)
        else:
            # Mensaje de texto - enviar instrucciones
            return send_instructions(message_data)
            
    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
        return jsonify({'status': 'error'}), 500

# Extraer datos del mensaje
def extract_message_data(data):
    """Extraer datos relevantes del mensaje de WhatsApp"""
    try:
        entry = data.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value = changes.get('value', {})
        messages = value.get('messages', [{}])
        message = messages[0]
        
        return {
            'from': message.get('from', 'unknown_user'), # Número del usuario que envió el mensaje
            'message_id': message.get('id', 'unknown_id'), # ID del mensaje
            'timestamp': message.get('timestamp', '0'), # # Timestamp del mensaje
            'has_media': 'image' in message.get('type', ''), # Verificar si el mensaje tiene imagen
            'media_id': message.get('image', {}).get('id') if 'image' in message.get('type', '') else None, # ID de la media si existe
            'message_type': message.get('type', 'text') # Tipo de mensaje
        }
    except Exception as e:
        logging.error(f"Error extrayendo datos del mensaje: {e}")
        return {'from': 'unknown', 'has_media': False}

# Procesar mensaje con imagen
def process_image_message(message_data):
    """Procesar mensaje con imagen """
    try:
        # DESCARGAR IMAGEN  DE WHATSAPP
        image_data = download_whatsapp_image(message_data['media_id']) # Descargar imagen usando media_id
        
        if not image_data:
            return send_text_message(message_data['from'], "❌ Error al descargar la imagen. Por favor intenta nuevamente.")
        
        # Subir a Cloud Storage
        file_name = f"{message_data['from']}_{message_data['message_id']}.jpg"
        image_url = upload_to_gcs(image_data, file_name)
        
        # Publicar mensaje en Pub/Sub
        publish_to_pubsub({
            'user_id': message_data['from'],
            'image_path': image_url,
            'message_id': message_data['message_id'],
            'timestamp': message_data['timestamp']
        })
        
        # Enviar mensaje de confirmación
        send_text_message(message_data['from'], "🔄 Procesando tu imagen... Esto puede tomar unos segundos.")
        
        return jsonify({'status': 'processing'}), 200
        
    except Exception as e:
        logging.error(f"Error procesando imagen: {e}")
        return send_text_message(message_data['from'], "❌ Error al procesar la imagen. Por favor intenta con otra foto.")

# Descargar imagen de WhatsApp Business API
def download_whatsapp_image(media_id):
    """ DESCARGAR IMAGEN REAL DE WHATSAPP BUSINESS API"""
    try:
        if not WHATSAPP_ACCESS_TOKEN:
            logging.error("WHATSAPP_ACCESS_TOKEN no configurado")
            return None
            
        # Obtener URL de la media con el token de acceso
        media_url = f"https://graph.facebook.com/v17.0/{media_id}/"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"
        }
        
        response = requests.get(media_url, headers=headers)
        if response.status_code != 200:
            logging.error(f"Error obteniendo media URL: {response.status_code} - {response.text}")
            return None
            
        media_data = response.json()
        download_url = media_data.get('url')
        
        if not download_url:
            logging.error("No se pudo obtener URL de descarga")
            return None
            
        # Descargar la imagen desde la URL obtenida
        image_response = requests.get(download_url, headers=headers)
        if image_response.status_code != 200:
            logging.error(f"Error descargando imagen: {image_response.status_code}")
            return None
            
        return image_response.content
        
    except Exception as e:
        logging.error(f"Error en download_whatsapp_image: {e}")
        return None

# Subir imagen a Cloud Storage
def upload_to_gcs(image_data, file_name):
    """Subir imagen a Cloud Storage"""
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_name)
    blob.upload_from_string(image_data, content_type='image/jpeg')
    return f"gs://{BUCKET_NAME}/{file_name}" # Retornar la ruta GCS de la imagen subida ejmplo: gs://bucket-name/file-name.jpg

# Publicar mensaje en Pub/Sub
def publish_to_pubsub(message_data): 
    """Publicar mensaje en Pub/Sub para procesamiento"""
    topic_path = publisher.topic_path(os.environ.get('GCP_PROJECT', 'prj-botlabs-dev'), TOPIC_NAME) 
    future = publisher.publish(
        topic_path,
        json.dumps(message_data).encode('utf-8')
    )
    message_id = future.result()
    logging.info(f"Mensaje publicado en Pub/Sub: {message_id}")
    return message_id

# Enviar mensaje de texto a WhatsApp
def send_text_message(user_id, text):
    """ENVIAR MENSAJE DE TEXTO REAL A WHATSAPP"""
    try:
        if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            logging.error("Configuración de WhatsApp incompleta")
            return jsonify({'status': 'error'}), 500
            
        url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        
        headers = {
            'Authorization': f'Bearer {WHATSAPP_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": user_id,
            "text": {"body": text}
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            logging.info(f"Mensaje enviado a {user_id}")
            return jsonify({'status': 'message_sent'}), 200
        else:
            logging.error(f"Error enviando mensaje: {response.status_code} - {response.text}")
            return jsonify({'status': 'error'}), 500
            
    except Exception as e:
        logging.error(f"Error en send_text_message: {e}")
        return jsonify({'status': 'error'}), 500

def send_instructions(message_data):
    """Enviar instrucciones al usuario"""
    instructions = """
📱 *AIASIGNA - Verificador de Productos*

Para verificar un producto, envía una foto clara que muestre:
• Etiqueta frontal
• Código de barras  
• Sellos de seguridad

Ejemplo: 📸 [foto del producto]
"""
    return send_text_message(message_data['from'], instructions)