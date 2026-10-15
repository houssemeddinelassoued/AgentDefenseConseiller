# Ouvre le tunnel ngrok vers l'Ollama du poste, pour la version web (Streamlit Cloud).
# Prérequis : Ollama lancé, ngrok configuré (ngrok config add-authtoken) et ngrok-politique.yml rempli.
$domaine = "neatly-reggae-spotter.ngrok-free.dev"
$politique = Join-Path $PSScriptRoot "ngrok-politique.yml"
if (-not (Test-Path $politique)) { throw "Copiez ngrok-politique.exemple.yml en ngrok-politique.yml et choisissez un mot de passe." }
ngrok http 11434 --url="https://$domaine" --host-header="localhost:11434" --traffic-policy-file="$politique"
