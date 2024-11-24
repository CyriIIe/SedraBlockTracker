import json
import time
import sqlite3
import subprocess
import logging
from telegram import Bot
import signal
import sys
import concurrent.futures
import asyncio

# Remplacez par votre token de bot Telegram
token = 'BOT_TOKEN'
# Instanciez le bot Telegram
bot = Bot(token=token)

# Configurer le logging pour afficher les logs en console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Fonction pour gérer l'interruption par Ctrl+C
def signal_handler(sig, frame):
    logging.info("Interruption reçue. Arrêt du bot...")
    sys.exit(0)

# Assigner le gestionnaire de signal pour l'interruption par Ctrl+C
signal.signal(signal.SIGINT, signal_handler)

# Fonction pour interroger le daemon Sedra via sedractl
async def check_block_rewards():
    # Connexion à la base de données SQLite
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # Charger tous les utilisateurs en mémoire pour éviter les requêtes répétées
    cursor.execute("SELECT username, address FROM users")
    users = cursor.fetchall()
    user_dict = {address: username for username, address in users}
    last_user_update_time = time.time()
    logging.info("Les utilisateurs ont été chargés depuis la base de données.")
    
    # Stocker le hash du dernier bloc vérifié
    last_checked_hash = None
    
    while True:
        try:
            # Recharger les utilisateurs toutes les 5 minutes
            if time.time() - last_user_update_time > 300:
                cursor.execute("SELECT username, address FROM users")
                users = cursor.fetchall()
                user_dict = {address: username for username, address in users}
                last_user_update_time = time.time()
                logging.info("Les utilisateurs ont été rechargés depuis la base de données.")
                
            # Utiliser un pool de threads pour exécuter des commandes en parallèle
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Obtenir le hash du bloc le plus récent (tip hash) via la commande ./sedractl GetSelectedTipHash
                future_tip_hash = executor.submit(subprocess.run, ['./sedractl', 'GetSelectedTipHash'], capture_output=True, text=True)
                result = future_tip_hash.result()

                if result.returncode != 0:
                    logging.error(f"Erreur lors de la récupération du tip hash: {result.stderr}")
                    await asyncio.sleep(0.01)
                    continue
                
                # Vérifier si la sortie est un JSON valide
                try:
                    tip_data = json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    logging.error(f"Erreur lors du parsing du JSON pour le tip hash: {e}")
                    await asyncio.sleep(0.01)
                    continue
                
                current_tip_hash = tip_data.get('getSelectedTipHashResponse', {}).get('selectedTipHash', '')
                
                # Vérifier si le dernier bloc a déjà été traité
                if current_tip_hash == last_checked_hash:
                    await asyncio.sleep(0.01)
                    continue
                
                # Préparer la commande pour obtenir les détails du dernier bloc via ./sedractl GetBlock
                logging.info(f"Récupération des détails du bloc: {current_tip_hash}")
                future_block = executor.submit(subprocess.run, ['./sedractl', 'GetBlock', current_tip_hash, 'true'], capture_output=True, text=True)
                result = future_block.result()

                if result.returncode != 0:
                    logging.error(f"Erreur lors de la récupération du bloc {current_tip_hash}: {result.stderr}")
                    await asyncio.sleep(0.01)
                    continue
                
                # Vérifier si la sortie est un JSON valide
                try:
                    block_data = json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    logging.error(f"Erreur lors du parsing du JSON pour le bloc: {e}")
                    await asyncio.sleep(0.01)
                    continue
                
                block = block_data.get('getBlockResponse', {}).get('block', {})
                logging.info(f"Détails du bloc {current_tip_hash} récupérés avec succès.")
                
                # Vérifier la transaction de récompense (coinbase)
                transactions = block.get('transactions', [])
                for transaction in transactions:
                    outputs = transaction.get('outputs', [])
                    for output in outputs:
                        # Vérifier si la transaction est une transaction coinbase
                        verbose_data = output.get('verboseData', {})
                        miner_address = verbose_data.get('scriptPublicKeyAddress', '')
                        reward_raw = output.get('amount', 0)
                        
                        # Conversion de la récompense en SDR avec 8 décimales
                        reward = float(reward_raw) / 10**8
                        formatted_reward = "{:.8f}".format(reward)
                        
                        # Vérifier si l'adresse appartient à un utilisateur connu
                        if miner_address in user_dict:
                            username = user_dict[miner_address]
                            block_link = f"https://explorer.sedracoin.com/blocks/{current_tip_hash}"
                            message = (
                                f"Félicitations {username}, vous avez trouvé un nouveau bloc ! 🎉\n"
                                f"Récompense : {formatted_reward} SDR\n"
                                f"[Voir le détail du bloc sur l'explorateur]({block_link})"
                            )
                            await bot.send_message(chat_id='CHAT_ID', message_thread_id=61, text=message, parse_mode='Markdown')
                            logging.info(f"Notification envoyée à {username}: {message}")
                
                # Mettre à jour le dernier hash vérifié
                last_checked_hash = current_tip_hash
        except Exception as e:
            logging.error(f"Erreur lors de la vérification du bloc {current_tip_hash}: {e}")
        
        # Attendre un certain temps avant de refaire la vérification (toutes les 0.01 secondes pour minimiser le risque de rater un bloc)
        await asyncio.sleep(0.01)

# Lancer la fonction de vérification
async def main():
    # Créer un processus de vérification en boucle
    await check_block_rewards()

if __name__ == "__main__":
    asyncio.run(main())

