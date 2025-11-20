# Respuesta a usuarios WhatsApp
import functions_framework
from google.cloud import firestore
import os
import requests
import logging
import json
from flask import Flask
 
# Crear app Flask para Gunicorn
app = Flask(__name__)
 
# Clientes GCP
firestore_client = firestore.Client()
WHATSAPP_API_URL = "https://graph.facebook.com/v17.0/"
WHATSAPP_ACCESS_TOKEN = os.environ.get('WHATSAPP_ACCESS_TOKEN')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')
 
# Mantener la función de Cloud Functions para compatibilidad
@functions_framework.http
def send_response(request):
    """Función para enviar respuestas a WhatsApp"""
   
    if request.method != 'POST':
        return 'Método no permitido', 405
   
    try:
        data = request.get_json()
        user_id = data['user_id']
        message_id = data.get('message_id')
       
        logging.info(f"Buscando resultados para usuario: {user_id}")
       
        # Obtener el último resultado de Firestore para el usuario
        result = get_latest_analysis_result(user_id, message_id)
       
        if not result:
            logging.warning(f"No se encontraron resultados para {user_id}")
            send_whatsapp_message(user_id, "❌ No se encontraron resultados de análisis. Por favor envía otra imagen.")
            return 'Resultado no encontrado', 404
       
        # Formatear mensaje de respuesta
        message = format_whatsapp_message(result)
       
        #  ENVIAR A WHATSAPP
        send_whatsapp_message(user_id, message)
       
        logging.info(f"Respuesta enviada a {user_id}")
        return 'Mensaje enviado', 200
       
    except Exception as e:
        logging.error(f"Error enviando respuesta: {e}")
        return 'Error interno', 500
 
# Ruta Flask para health checks
@app.route('/')
def health_check():
    return 'OK', 200

# Descargar imagen de WhatsApp
@app.route('/send-response', methods=['POST'])
def send_response_endpoint():
    """Endpoint Flask para enviar respuestas"""
    return send_response(request)
 
# ... (el resto del código se mantiene igual)
def get_latest_analysis_result(user_id, message_id=None):
    """Obtener resultado del análisis de Firestore"""
    try:
        query = firestore_client.collection('analysis_results')\
            .where('user_id', '==', user_id)\
            .where('status', '==', 'completed')
       
        if message_id:
            query = query.where('message_id', '==', message_id)
           
        docs = query.order_by('timestamp', direction=firestore.Query.DESCENDING)\
            .limit(1)\
            .stream()
       
        for doc in docs:
            return doc.to_dict()
        return None
       
    except Exception as e:
        logging.error(f"Error consultando Firestore: {e}")
        return None
 
def format_whatsapp_message(result):
    """Formatear mensaje para WhatsApp"""
    probability = result.get('probability', 0)
    anomalies = result.get('anomalies', [])
   
    # Emojis y estado basados en probabilidad
    if probability < 30:
        emoji = "✅"
        status = "BAJA PROBABILIDAD"
        recommendation = "El producto parece auténtico."
    elif probability < 70:
        emoji = "⚠️"
        status = "PROBABILIDAD MEDIA"
        recommendation = "Se recomienda verificación adicional."
    else:
        emoji = "❌"
        status = "ALTA PROBABILIDAD"
        recommendation = "Se recomienda no usar el producto y contactar al fabricante."
   
    message = f"""
{emoji} *ANÁLISIS COMPLETADO* {emoji}
 
*Probabilidad de falsificación:* {probability}%
*Estado:* {status}
 
*Anomalías detectadas:*
"""
   
    if anomalies:
        for i, anomaly in enumerate(anomalies[:5], 1):
            message += f"• {anomaly}\n"
    else:
        message += "• No se detectaron anomalías significativas\n"
   
    message += f"""
*Recomendación:* {recommendation}
 
---
*AIASIGNA - Sistema de Verificación Automática*
_Este análisis es preliminar. Para confirmación definitiva consulte con un especialista._
"""
   
    return message
 
def send_whatsapp_message(user_id, message):
    """ ENVÍO  A WHATSAPP BUSINESS API"""
    try:
        if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            logging.error("WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID no configurados")
            return False
           
        url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
       
        headers = {
            'Authorization': f'Bearer {WHATSAPP_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
       
        payload = {
            "messaging_product": "whatsapp",
            "to": user_id,
            "text": {"body": message}
        }
       
        response = requests.post(url, json=payload, headers=headers, timeout=10)
       
        if response.status_code == 200:
            logging.info(f"Mensaje de respuesta enviado exitosamente a {user_id}")
            return True
        else:
            logging.error(f"Error enviando mensaje a WhatsApp: {response.status_code} - {response.text}")
            return False
           
    except requests.exceptions.Timeout:
        logging.error("Timeout enviando mensaje a WhatsApp")
        return False
    except Exception as e:
        logging.error(f"Error inesperado en send_whatsapp_message: {e}")
        return False
 
# Punto de entrada para Gunicorn
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)