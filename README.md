# 🎯 AIASIGNA - Sistema de Verificación de Productos

Sistema serverless para detectar productos falsificados mediante WhatsApp y Google Cloud Platform.

## 🏗️ Arquitectura

WhatsApp → Cloud Functions → Cloud Storage → Pub/Sub → Vision API → Firestore → WhatsApp

📱 Uso
Envía una foto de producto (Bayer o FLA) por WhatsApp

Recibe análisis automático en segundos

Obtén probabilidad de falsificación y anomalías detectadas

Características
Detección automática Bayer/FLA

Análisis con Cloud Vision API

Sistema de pesos dinámicos

Arquitectura serverless escalable

Integración WhatsApp Business API