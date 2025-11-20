Write-Host "========================================" -ForegroundColor Blue
Write-Host "   VERIFICACION ENTORNO AIASIGNA" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue
Write-Host ""

Write-Host "Proyecto: " -NoNewline
gcloud config get-value project

Write-Host "Cuenta: " -NoNewline
gcloud config get-value account

Write-Host "Region: " -NoNewline
gcloud config get-value compute/region

Write-Host ""
Write-Host "✅ Firestore confirmado:" -ForegroundColor Green
gcloud firestore databases list --project=prj-botlabs-dev --format="value(name, locationId)"

Write-Host ""
Write-Host "✅ APIs disponibles:" -ForegroundColor Green
gcloud services list --enabled --project=prj-botlabs-dev --filter="name:cloudfunctions OR name:run OR name:vision OR name:firestore OR name:storage OR name:pubsub" --format="value(NAME)"

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
pause
