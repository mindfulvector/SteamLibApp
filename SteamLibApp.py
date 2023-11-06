from flask import Flask, render_template
from datetime import datetime, timedelta
import requests
import sqlite3
import time
from typing import List, Dict
import pprint
import os

# See README file for how to get this value and your library ID!
STEAM_API_KEY = os.environ.get('STEAM_API_KEY')
DEFAULT_STEAM_LIBRARY_ID = os.environ.get('DEFAULT_STEAM_LIBRARY_ID')

pp = pprint.PrettyPrinter(indent=2)

app = Flask(__name__)
DATABASE = 'steam_cache.db'

stat_api_calls = 0
stat_api_calls_last_rest = 0

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS library (
            steamid TEXT NOT NULL,
            appid INTEGER NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            PRIMARY KEY (steamid, appid)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS app_details (
            appid INTEGER PRIMARY KEY,
            title TEXT,
            image_urls TEXT,
            last_updated TIMESTAMP NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

create_tables()

def get_steam_library(steamid, api_key):
    conn = get_db_connection()
    current_time = datetime.now()
    games = conn.execute('''
        SELECT appid FROM library WHERE steamid = ? AND last_updated > ?
    ''', (steamid, current_time - timedelta(days=1))).fetchall()  # Cache for 1 day
    
    if games:
        return [dict(game)['appid'] for game in games]
    else:
        url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        params = {
            'key': api_key,
            'steamid': steamid,
            'format': 'json',
            'include_appinfo': True
        }
        response = requests.get(url, params=params)
        library = response.json().get('response', {}).get('games', [])
        games = [game['appid'] for game in library]
        
        conn.execute('DELETE FROM library WHERE steamid = ?', (steamid,))
        conn.executemany('''
            INSERT INTO library (steamid, appid, last_updated) VALUES (?, ?, ?)
        ''', [(steamid, game, current_time) for game in games])
        conn.commit()
        return games

def get_steam_app_details(appid):
    conn = get_db_connection()
    app = conn.execute('''
        SELECT appid,title,image_urls FROM app_details WHERE appid = ? AND last_updated > ?
    ''', (appid, datetime.now() - timedelta(days=30))).fetchone()  # Cache for 30 days
    
    if app:
        result = dict(app)
        result['image_urls'] = result['image_urls'].split('|')
        return dict(app)
    else:
        global stat_api_calls, stat_api_calls_last_rest
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
        response = requests.get(url)
        data = response.json()
        stat_api_calls += 1
        ncols=30
        print(f"\033[F\033[{ncols}G API call...{appid}")
        if None != data and str(appid) in data and data[str(appid)]['success']:
            game_data = data[str(appid)]['data']
            title = game_data.get('name')
            image_urls = [screenshot['path_full'] for screenshot in game_data['screenshots']] if 'screenshots' in game_data else None
            if image_urls == None:
                conn.execute('''
                    INSERT OR REPLACE INTO app_details (appid, title, image_urls, last_updated) 
                    VALUES (?, ?, ?, ?)
                    ''', (appid, title, '[]', datetime.now()))
            else:
                conn.execute('''
                    INSERT OR REPLACE INTO app_details (appid, title, image_urls, last_updated) 
                    VALUES (?, ?, ?, ?)
                ''', (appid, title, '|'.join(image_urls), datetime.now()))
                conn.commit()
            return {'title': title, 'image_urls': image_urls}
        else:
            print("API call failed!")
            pp.pprint(response)
            pp.pprint(data)
        return None



# 76561197983666621
@app.route('/library/')
@app.route('/library/<int:steamid>')
def library(steamid=0):
    global stat_api_calls, stat_api_calls_last_rest
    if 0 == steamid:
        steamid = DEFAULT_STEAM_LIBRARY_ID
    games = get_steam_library(steamid, STEAM_API_KEY)
    game_count = int(len(games))

    game_details = []
    game_no = 0
    for appid in games:
        game_no += 1
        print(f"{game_no}/{game_count} ({stat_api_calls}) API calls)")
        
        details = get_steam_app_details(appid)
        if details:
            game_details.append(details)

        # wait for awhile to spread out calls
        if (stat_api_calls > 0) and (0 == stat_api_calls % 50) and (stat_api_calls_last_rest < stat_api_calls):
            print("Sheesh, give it a rest!")
            stat_api_calls_last_rest = stat_api_calls
            time.sleep(15)

    return render_template('library.html', games=game_details)

if __name__ == '__main__':
    app.run(debug=True)
