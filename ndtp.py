import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import logging
import datetime
import json

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = '7900385979:AAGC0ILgiaLj6NlXNTypx_Cd_XC5Bj8hONA'
client_id = 'fa6871cc71394b7591728a615a0236e8'
client_secret = '758cc894969c4026832f9037ecab3c82'
redirect_uri = 'http://localhost:8888/callback'
scope = 'playlist-modify-public user-read-private'


class SpotifyManager:
    def __init__(self, client_id, client_secret, redirect_uri, scope):
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope + ' user-top-read',
            cache_path='.spotify_token_cache'))
        self.user_history = {}
        self._load_history()

    def _load_history(self):
        try:
            with open('user_history.json', 'r') as f:
                self.user_history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.user_history = {}

    def _save_history(self):
        with open('user_history.json', 'w') as f:
            json.dump(self.user_history, f)

    def get_auth_url(self):
        return self.sp.auth_manager.get_authorize_url()

    def handle_callback(self, code):
        token_info = self.sp.auth_manager.get_cached_token(code)
        self.sp.auth_manager.cache_token(token_info)
        return token_info

    def create_playlist(self, user_id, genre, mood):
        query = f"{genre} {mood}"
        results = self.sp.search(q=query, type='track', limit=25)

        if not results['tracks']['items']:
            raise ValueError("Треки не найдены")

        user = self.sp.current_user()
        playlist = self.sp.user_playlist_create(
            user['id'],
            f"{genre} - {mood}",
            public=True,
            description='Плейлист, созданный с помощью Spotify Telegram Bot')

        track_uris = [track['uri'] for track in results['tracks']['items']]
        self.sp.playlist_add_items(playlist['id'], track_uris)

        return playlist

    def save_user_preference(self, user_id, genre, mood):
        # Сохранение предпочтений пользователя в историю
        if not genre or not mood:
            raise ValueError("Жанр и настроение не могут быть пустыми.")
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        try:
            self.user_history[user_id].append({'genre': genre,
            'mood': mood,
            'timestamp': datetime.datetime.now()})
        except Exception as e:
                print(f"Ошибка сохранения предпочтений: {e}")
                self._save_history()

    def get_user_top_tracks(self, user_id, limit=5):
        try:
            top_tracks = self.sp.current_user_top_tracks(limit=limit)
            return top_tracks['items']
        except Exception as e:
            logger.error(f"Ошибка получения топ-треков: {e}")
            return None

    def _mood_to_valence(self, mood):
        mood_map = {'Радостное': 0.9,
            'Грустное': 0.2,
            'Энергичное': 0.8,
            'Расслабленное': 0.5,
            'Любовь': 0.7,
            'Тревожное': 0.3,
            'Скука': 0.4}
        return mood_map.get(mood, 0.5)

    def get_recommendations(self, user_id, limit=7):
        if user_id not in self.user_history or len(self.user_history[user_id]) < 1:
            return None  # Недостаточно данных для рекомендаций

            # Анализируем историю
        genres = {}
        moods = {}
        for entry in self.user_history[user_id][-5:]:
            genres[entry['genre']] = genres.get(entry['genre'], 0) + 1
            moods[entry['mood']] = moods.get(entry['mood'], 0) + 1

        # Определяем самые популярные жанр и настроение
        top_genre = max(genres.items(), key=lambda x: x[1])[0]
        top_mood = max(moods.items(), key=lambda x: x[1])[0]

        # Получаем рекомендации от Spotify
        try:
            logger.info(f"Запрос рекомендаций с жанром: {top_genre}, "
                        f"настроением: {top_mood}")
            recs = self.sp.recommendations(seed_genres=[top_genre.lower()],
                limit=limit,
                target_valence=self._mood_to_valence(top_mood))
            return recs['tracks']
        except Exception as e:
            logger.error(f"Ошибка получения рекомендаций: {e}")
            logger.info(f"top_genre: {top_genre}, top_mood: {top_mood}")
            return None


class KeyboardManager:
    @staticmethod
    def genre_keyboard():
        keyboard = InlineKeyboardMarkup()
        genres = ['Рок', 'Поп', 'Рэп', 'Метал', 'Классика', 'Джаз']
        for genre in genres:
            keyboard.add(InlineKeyboardButton(genre, callback_data=f'genre_{genre}'))
        return keyboard

    @staticmethod
    def mood_keyboard():
        keyboard = InlineKeyboardMarkup()
        moods = ['Радостное', 'Грустное', 'Энергичное', 'Расслабленное', 'Любовь',
                 'Тревожное', 'Скука']
        for mood in moods:
            keyboard.add(InlineKeyboardButton(mood, callback_data=f'mood_{mood}'))
        return keyboard


class MusicBot:
    def __init__(self, token, spotify_manager):
        self.bot = telebot.TeleBot(token)
        self.spotify = spotify_manager
        self.user_data = {}
        self._register_handlers()

    def _register_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start(message):
            self.user_data[message.from_user.id] = {'genre': None, 'mood': None}

            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton('Создать плейлист',
                                     callback_data='choose_genre'),
                InlineKeyboardButton('Помощь', callback_data='help'))
            self.bot.send_message(
                message.chat.id,
                f'Привет, {message.from_user.first_name}! С помощью данного бота вы '
                f'можете выбрать свое настроение и предпочтения в музыке, '
                f'а бот сгенерирует плейлист, на основе введенных данных. '
                f'Если вам что-то не понятно, нажмите кнопку "Помощь" '
                f'или используйте /help для получения списка команд.',
                reply_markup=keyboard)

        @self.bot.message_handler(commands=['help'])
        def help(message):
            self.bot.send_message(
                message.chat.id,
                'Данный бот создан для упрощения выбора пользователей'
                'и экономии их времени. Нажмите кнопку создать плейлист для '
                'начала работы.\n\n'
                'Доступные команды:\n'
                '/start - Начать работу\n'
                '/help - Получить помощь\n'
                '/create - Создать плейлист\n\n'
                'Просто выбери жанр и настроение, а я создам подходящий вам плейлист :)')

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            user_id = call.from_user.id
            if user_id not in self.user_data:
                self.user_data[user_id] = {'genre': None, 'mood': None}

            if call.data == 'choose_genre':
                self.bot.send_message(
                    call.message.chat.id,
                    'Для начала выберите жанр:',
                    reply_markup=KeyboardManager.genre_keyboard())
            elif call.data.startswith('genre_'):
                genre = call.data.split('_')[1]
                self.user_data[user_id]['genre'] = genre
                self.bot.send_message(
                    call.message.chat.id,
                    f'Хорошо, вы выбрали жанр {genre}. Теперь выберите ваше настроение:',
                    reply_markup=KeyboardManager.mood_keyboard())
            elif call.data.startswith('mood_'):
                mood = call.data.split('_')[1]
                self.user_data[user_id]['mood'] = mood
                self.bot.send_message(
                    call.message.chat.id,
                    f'Отлично! Ваш выбор зафиксирован.\n'
                    f'Жанр: {self.user_data[user_id]["genre"]}\n'
                    f'Настроение: {mood}\n\n'
                    'Теперь можем переходит к генерации плейлиста. Пожалуйста, '
                    'используйте команду /create')
            elif call.data == 'help':
                help(call.message)

        @self.bot.message_handler(commands=['recommend'])
        def recommend_tracks(message):
            user_id = message.from_user.id
            try:
                # Проверяем авторизацию
                token_info = self.spotify.sp.auth_manager.get_cached_token()
                if not token_info:
                    auth_url = self.spotify.get_auth_url()
                    self.bot.send_message(message.chat.id,
                                          "Сначала авторизуйтесь в Spotify: " +
                                          auth_url)
                    return
                # Получаем рекомендации
                recommendations = self.spotify.get_recommendations(user_id)
                if not recommendations:
                    self.bot.send_message(message.chat.id,
                                          "Пока недостаточно данных для "
                                          "рекомендаций. "
                                          "Создайте еще несколько плейлистов!")
                return

                # Формируем сообщение с рекомендациями
                msg = "Вам могут понравиться:\n\n"
                for i, track in enumerate(recommendations, 1):
                    artists = ", ".join([a['name'] for a in track['artists']])
                    msg += f"{i}. {track['name']} - {artists}\n"
                    msg += f"🔗 {track['external_urls']['spotify']}\n\n"

                self.bot.send_message(message.chat.id, msg)

            except Exception as e:
                logger.error(f"Ошибка рекомендаций: {e}")
                self.bot.send_message(message.chat.id,
                                      "Произошла ошибка при получении"
                                      "рекомендаций")

        @self.bot.message_handler(commands=['create'])
        def create_playlist(message):
            user_id = message.from_user.id

            if (user_id not in self.user_data or not self.user_data[user_id]['genre']
                    or not self.user_data[user_id]['mood']):
                self.bot.send_message(message.chat.id, 'Перед созданием плейлиста '
                                                       'выберите жанр и настроение!')
                return

            try:
                token_info = self.spotify.sp.auth_manager.get_cached_token()
                if not token_info:
                    auth_url = self.spotify.get_auth_url()
                    self.bot.send_message(
                        message.chat.id,
                        f'Сначала вам нужно авторизоваться в Spotify:\n{auth_url}\n\n'
                        'После авторизации вы будете перенаправлен на localhost - '
                        'просто скопируйте URL и отправьте мне. Я перенаправлю '
                        'вас сразу к готовому плейлисту ^^')
                    return

                playlist = self.spotify.create_playlist(
                    user_id,
                    self.user_data[user_id]['genre'],
                    self.user_data[user_id]['mood'])

                self.spotify.save_user_preference(user_id,
                    self.user_data[user_id]['genre'],
                    self.user_data[user_id]['mood'])

                self.bot.send_message(
                    message.chat.id,
                    f'Ваш плейлист готов!\n'
                    f'Название: {playlist["name"]}\n'
                    f'Ссылка: {playlist["external_urls"]["spotify"]}')

            except Exception as e:
                logger.error(f'Ошибка при создании плейлиста: {e}')
                self.bot.send_message(message.chat.id, f'Произошла ошибка: {str(e)}')

        @self.bot.message_handler(func=lambda m: 'localhost:8888/callback' in m.text)
        def handle_callback(message):
            try:
                code = message.text.split('code=')[1].split('&')[0]
                self.spotify.handle_callback(code)
                self.bot.send_message(message.chat.id, 'Авторизация прошла успешно! '
                                                       'Теперь можешь создать плейлист.')
            except Exception as e:
                self.bot.send_message(message.chat.id, f'Ошибка авторизации: {str(e)}')

    def run(self):
        logger.info('Бот запущен')
        self.bot.polling(none_stop=True)

if __name__ == '__main__':

    # Запуск бота
    spotify_manager = SpotifyManager(client_id, client_secret, redirect_uri, scope)
    bot = MusicBot(TOKEN, spotify_manager)
    bot.run()