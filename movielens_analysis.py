import re
from datetime import datetime, timezone
from collections import Counter
import sys
import os
import pytest
import requests
from collections import Counter

def _split_csv_line(line, delimiter=','):
    """
    Разбивает строку CSV на поля, учитывая двойные кавычки.
    Возвращает список полей.
    """
    fields = []
    current_field = ''
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            fields.append(current_field.strip('"'))
            current_field = ''
        else:
            current_field += char
    fields.append(current_field.strip('"'))
    return fields

def _parse_csv(filepath, delimiter=',', nrows=1000):
    try:
        with open(filepath, encoding='utf-8') as file:
            header_line = file.readline().strip()
            header = _split_csv_line(header_line, delimiter)
            rows = []
            for line in file:
                if nrows is not None and len(rows) >= nrows:
                    break
                line = line.strip()
                if not line:
                    continue
                rows.append(_split_csv_line(line, delimiter))
        return header, rows
    except FileNotFoundError:
        print(f"Warning: File {filepath} not found.")
        return [], []

class Ratings:
    def __init__(self, path_to_ratings, path_to_movies):
        # Загрузка рейтингов с защитой
        _, raw_ratings = _parse_csv(path_to_ratings, nrows=1000)
        self.ratings = []
        for row in raw_ratings:
            try:
                self.ratings.append({
                    'userId': int(row[0]),
                    'movieId': int(row[1]),
                    'rating': float(row[2]),
                    'timestamp': int(row[3])
                })
            except (ValueError, IndexError):
                continue

        # Загрузка всех названий фильмов с защитой
        # Для корректного отображения названий фильмов загружаем весь movies.csv,
        # так как в первых 1000 рейтингах могут встретиться фильмы за пределами первых 1000 строк movies.
        _, raw_movies = _parse_csv(path_to_movies, nrows=None)
        self.movie_titles = {}
        for row in raw_movies:
            try:
                movie_id = int(row[0])
                title = row[1]
                self.movie_titles[movie_id] = title
            except (ValueError, IndexError):
                continue

        self.movies = self.Movies(self)
        self.users = self.Users(self)

    class Movies:
        def __init__(self, parent):
            self.parent = parent

        def _group_by_movie(self):
            """Собирает все оценки, сгруппированные по movieId."""
            groups = {}
            for rating_record in self.parent.ratings:
                movie_id = rating_record['movieId']
                if movie_id not in groups:
                    groups[movie_id] = []
                groups[movie_id].append(rating_record['rating'])
            return groups

        def dist_by_year(self):
            """Распределение оценок по годам (год из timestamp)."""
            years = {}
            for rating_record in self.parent.ratings:
                year = datetime.fromtimestamp(rating_record['timestamp'], tz=timezone.utc).year
                if year in years:
                    years[year] += 1
                else:
                    years[year] = 1
            sorted_years = sorted(years.keys())
            result = {}
            for year in sorted_years:
                result[year] = years[year]
            return result

        def dist_by_rating(self):
            """Распределение оценок (rating -> count)."""
            distribution = {}
            for rating_record in self.parent.ratings:
                rating_value = rating_record['rating']
                if rating_value in distribution:
                    distribution[rating_value] += 1
                else:
                    distribution[rating_value] = 1
            sorted_ratings = sorted(distribution.keys())
            result = {}
            for rating_value in sorted_ratings:
                result[rating_value] = distribution[rating_value]
            return result

        def top_by_num_of_ratings(self, top_n):
            """Топ-n фильмов по количеству оценок."""
            groups = self._group_by_movie()
            rating_counts = {}
            for movie_id, ratings_list in groups.items():
                rating_counts[movie_id] = len(ratings_list)
            sorted_movie_list = sorted(rating_counts.items(), key=lambda pair: pair[1], reverse=True)
            result = {}
            for movie_id, count in sorted_movie_list[:top_n]:
                title = self.parent.movie_titles.get(movie_id, str(movie_id))
                result[title] = count
            return result

        def top_by_ratings(self, top_n, metric='average'):
            """Топ-n фильмов по средней или медианной оценке."""
            groups = self._group_by_movie()
            metrics = {}
            for movie_id, ratings_list in groups.items():
                if metric == 'average':
                    value = sum(ratings_list) / len(ratings_list)
                elif metric == 'median':
                    sorted_ratings = sorted(ratings_list)
                    count_ratings = len(sorted_ratings)
                    if count_ratings % 2 == 1:
                        value = sorted_ratings[count_ratings // 2]
                    else:
                        value = (sorted_ratings[count_ratings // 2 - 1] + sorted_ratings[count_ratings // 2]) / 2.0
                else:
                    raise ValueError("metric must be 'average' or 'median'")
                metrics[movie_id] = round(value, 2)
            sorted_movie_list = sorted(metrics.items(), key=lambda pair: pair[1], reverse=True)
            result = {}
            for movie_id, metric_value in sorted_movie_list[:top_n]:
                title = self.parent.movie_titles.get(movie_id, str(movie_id))
                result[title] = metric_value
            return result

        def top_controversial(self, top_n):
            """Топ-n фильмов по дисперсии оценок."""
            groups = self._group_by_movie()
            variances = {}
            for movie_id, ratings_list in groups.items():
                mean = sum(ratings_list) / len(ratings_list)
                variance = sum((rating_value - mean) ** 2 for rating_value in ratings_list) / len(ratings_list)
                variances[movie_id] = round(variance, 2)
            sorted_movie_list = sorted(variances.items(), key=lambda pair: pair[1], reverse=True)
            result = {}
            for movie_id, variance_value in sorted_movie_list[:top_n]:
                title = self.parent.movie_titles.get(movie_id, str(movie_id))
                result[title] = variance_value
            return result

    class Users(Movies):
        def __init__(self, parent):
            super().__init__(parent)

        def _group_by_user(self):
            """Собирает все оценки, сгруппированные по userId."""
            groups = {}
            for rating_record in self.parent.ratings:
                user_id = rating_record['userId']
                if user_id not in groups:
                    groups[user_id] = []
                groups[user_id].append(rating_record['rating'])
            return groups

        def dist_by_num_of_ratings(self):
            """Распределение пользователей по количеству оценок."""
            groups = self._group_by_user()
            user_counts = {}
            for user_id, ratings_list in groups.items():
                count = len(ratings_list)
                user_counts[user_id] = count
            distribution = {}
            for count in user_counts.values():
                if count in distribution:
                    distribution[count] += 1
                else:
                    distribution[count] = 1
            sorted_counts = sorted(distribution.keys())
            result = {}
            for count in sorted_counts:
                result[count] = distribution[count]
            return result

        def dist_by_avg_rating(self, metric='average'):
            """
            Распределение пользователей по средней или медианной оценке.
            Параметр metric: 'average' (по умолчанию) или 'median'.
            """
            groups = self._group_by_user()
            user_metric_values = {}
            for user_id, ratings_list in groups.items():
                if metric == 'average':
                    value = sum(ratings_list) / len(ratings_list)
                elif metric == 'median':
                    sorted_ratings = sorted(ratings_list)
                    count_ratings = len(sorted_ratings)
                    if count_ratings % 2 == 1:
                        value = sorted_ratings[count_ratings // 2]
                    else:
                        value = (sorted_ratings[count_ratings // 2 - 1] + sorted_ratings[count_ratings // 2]) / 2.0
                else:
                    raise ValueError("metric must be 'average' or 'median'")
                user_metric_values[user_id] = round(value, 2)

            distribution = {}
            for metric_value in user_metric_values.values():
                distribution[metric_value] = distribution.get(metric_value, 0) + 1

            sorted_keys = sorted(distribution.keys())
            result = {}
            for key in sorted_keys:
                result[key] = distribution[key]
            return result

        def top_controversial_users(self, top_n):
            """Топ-n пользователей по дисперсии оценок."""
            groups = self._group_by_user()
            variances = {}
            for user_id, ratings_list in groups.items():
                mean = sum(ratings_list) / len(ratings_list)
                variance = sum((rating_value - mean) ** 2 for rating_value in ratings_list) / len(ratings_list)
                variances[user_id] = round(variance, 2)
            sorted_user_list = sorted(variances.items(), key=lambda pair: pair[1], reverse=True)
            result = {}
            for user_id, variance_value in sorted_user_list[:top_n]:
                result[user_id] = variance_value
            return result


class Movies:
    def __init__(self, path_to_the_file):
        _, raw_movies = _parse_csv(path_to_the_file, nrows=1000)
        self.movies = []
        for row in raw_movies:
            try:
                movie_id = int(row[0])
                title = row[1]
                year = None
                if title.endswith(')') and '(' in title:
                    year_str = title[title.rfind('(')+1 : title.rfind(')')]
                    if year_str.isdigit() and len(year_str) == 4:
                        year = int(year_str)
                genres_str = row[2]
                if genres_str == '(no genres listed)':
                    genres = []
                else:
                    genres = genres_str.split('|')
                self.movies.append({
                    'movieId': movie_id,
                    'title': title,
                    'year': year,
                    'genres': genres
                })
            except (ValueError, IndexError):
                # Битая строка – пропускаем
                continue

    def dist_by_release(self):
        """Распределение фильмов по годам, сортировка по убыванию количества."""
        years = {}
        for movie in self.movies:
            year = movie['year']
            if year is not None:
                if year in years:
                    years[year] += 1
                else:
                    years[year] = 1
        sorted_years = sorted(years.items(), key=lambda pair: pair[1], reverse=True)
        result = {}
        for year, count in sorted_years:
            result[year] = count
        return result

    def dist_by_genres(self):
        genres = {}
        for movie in self.movies:
            for genre in movie['genres']:
                if genre in genres:
                    genres[genre] += 1
                else:
                    genres[genre] = 1
        sorted_genres = sorted(genres.items(), key=lambda pair: pair[1], reverse=True)
        result = {}
        for genre, count in sorted_genres:
            result[genre] = count
        return result

    def most_genres(self, top_n):
        movie_genre_counts = []
        for movie in self.movies:
            count = len(movie['genres'])
            movie_genre_counts.append((movie['title'], count))
        sorted_movies = sorted(movie_genre_counts, key=lambda pair: pair[1], reverse=True)
        result = {}
        for title, count in sorted_movies[:top_n]:
            result[title] = count
        return result


class Tags:
    """
    Analyzing data from tags.csv
    """
    def __init__(self, path_to_the_file):
        self.data = []
        _, rows = _parse_csv(path_to_the_file, nrows=1000)
        for row in rows:
            if len(row) < 4:
                continue
            try:
                record = {
                    'userId': int(row[0]),
                    'movieId': int(row[1]),
                    'tag': row[2],
                    'timestamp': int(row[3])
                }
                self.data.append(record)
            except (ValueError, IndexError):
                continue
        """
        Put here any fields that you think you will need.
        """
    def tag_list(self):
        tags = []
        for i in self.data:
            tag = i['tag']
            tags.append(tag)
        return tags

    def most_words(self, n):
        """
        The method returns top-n tags with most words inside. It is a dict 
 where the keys are tags and the values are the number of words inside the tag.
 Drop the duplicates. Sort it by numbers descendingly.
        """
        tags = self.tag_list()
        counts = {}
        for tag in set(tags):
            count = len(tag.split())
            counts[tag] = count
        big_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        big_tags = dict(big_tags[:n])
        return big_tags

    def longest(self, n):
        """
        The method returns top-n longest tags in terms of the number of characters.
        It is a list of the tags. Drop the duplicates. Sort it by numbers descendingly.
        """
        tags = self.tag_list()
        counts = {}
        big_tags = []
        for tag in set(tags):
            count = len(tag)
            counts[tag] = count
        dict_tags = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        dict_tags = dict(dict_tags[:n])
        for i in dict_tags:
            big_tags.append(i)
        return big_tags

    def most_words_and_longest(self, n):
        """
        The method returns the intersection between top-n tags with most words inside and 
        top-n longest tags in terms of the number of characters.
        Drop the duplicates. It is a list of the tags.
        """
        top_most_words = self.most_words(n).keys()
        top_longest = self.longest(n)
        big_tags = list(set(top_most_words) & set(top_longest))
        big_tags = big_tags[:n]
        return big_tags
        
    def most_popular(self, n):
        """
        The method returns the most popular tags. 
        It is a dict where the keys are tags and the values are the counts.
        Drop the duplicates. Sort it by counts descendingly.
        """
        tags = self.tag_list()
        tag_counts = Counter(tags)
        popular_tags = dict(tag_counts.most_common(n))
        return popular_tags
        
    def tags_with(self, word):
        """
        The method returns all unique tags that include the word given as the argument.
        Drop the duplicates. It is a list of the tags. Sort it by tag names alphabetically.
        """
        tags = self.tag_list()
        tags_with_word = []
        for i in set(tags):
            if word.lower() in i.lower():
                tags_with_word.append(i)
        tags_with_word.sort()
        return tags_with_word
    

class Links:
    """
    Analyzing data from links.csv
    """
    def __init__(self, path_to_the_file):
        self.data = []
        _, rows = _parse_csv(path_to_the_file, nrows=1000)
        for row in rows:
            if len(row) < 3:
                continue
            if not row[0] or not row[1] or not row[2]:
                continue
            try:
                record = {
                    'movieId': int(row[0]),
                    'imdbId': row[1],
                    'tmdbId': int(row[2])
                }
                self.data.append(record)
            except (ValueError, IndexError):
                continue
        """
        Put here any fields that you think you will need.
        """
    def get_movie_info(self, imdb_id):
        TMDB_API_KEY = "1c0f6233c178598ff3310e75ec385ac0"

        if TMDB_API_KEY.startswith("eyJ"):
            headers = {"Authorization": f"Bearer {TMDB_API_KEY}"}
            params = {}
        else:
            headers = {}
            params = {"api_key": TMDB_API_KEY}

        find_url = f"https://api.themoviedb.org/3/find/{imdb_id}"
        find_params = {**params, "external_source": "imdb_id"}
        try:
            resp = requests.get(find_url, headers=headers, params=find_params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return self._empty_movie_info()

        movies = data.get("movie_results", [])
        if not movies:
            return self._empty_movie_info()
        tmdb_id = movies[0]["id"]

        details_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
        try:
            resp = requests.get(details_url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            details = resp.json()
        except Exception:
            return self._empty_movie_info()

        credits_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/credits"
        director = "N/A"
        try:
            resp = requests.get(credits_url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            credits = resp.json()
            for person in credits.get("crew", []):
                if person.get("job") == "Director":
                    director = person.get("name", "N/A")
                    break
        except Exception:
            pass
        
        title = details.get("title", "N/A")
        budget = details.get("budget", 0)
        budget_str = f"${budget:,}" if budget > 0 else "N/A"
        revenue = details.get("revenue", 0)
        revenue_str = f"${revenue:,}" if revenue > 0 else "N/A"
        runtime_min = details.get("runtime", 0)
        runtime_str = self._format_runtime(runtime_min) if runtime_min > 0 else "N/A"

        return {
            "Title": title,
            "Director": director,
            "Budget": budget_str,
            "Cumulative Worldwide Gross": revenue_str,
            "Runtime": runtime_str
        }

    def _empty_movie_info(self):
        return {
            "Title": "N/A",
            "Director": "N/A",
            "Budget": "N/A",
            "Cumulative Worldwide Gross": "N/A",
            "Runtime": "N/A"
        }

    def _format_runtime(self, minutes):
        if minutes <= 0:
            return "N/A"
        h = minutes // 60
        m = minutes % 60
        if h == 0:
            return f"{m}m"
        if m == 0:
            return f"{h}h"
        return f"{h}h {m}m"
        

    def get_imdb(self, list_of_movies, list_of_fields):
        """
The method returns a list of lists [movieId, field1, field2, field3, ...] for the list of movies given as the argument (movieId).
        For example, [movieId, Director, Budget, Cumulative Worldwide Gross, Runtime].
        The values should be parsed from the IMDB webpages of the movies.
     Sort it by movieId descendingly.
        """
        imdb_info = []
        movie_to_imdb_map = {
            int(record['movieId']): str(record['imdbId']).strip() 
            for record in self.data
        }
        for movie_id in list_of_movies:
            movie_id_int = int(movie_id)
            if movie_id_int in movie_to_imdb_map:
                raw_imdb_id = movie_to_imdb_map[movie_id_int]
                imdb_id = 'tt' + raw_imdb_id.zfill(7)
                movie_data = self.get_movie_info(imdb_id)
                row = [movie_id_int]
                for field in list_of_fields:
                    value = movie_data.get(field, 'N/A')
                    row.append(value)
                imdb_info.append(row)
        imdb_info.sort(key=lambda x: x[0], reverse=True)
        return imdb_info
        
    def money_to_number(self, money_str):
        if money_str == 'N/A' or not money_str:
            return 0
        return int(money_str.replace('$', '').replace(',', ''))

    def runtime_to_minutes(self, runtime_str):
        if runtime_str == 'N/A' or not runtime_str:
            return 0
        minutes = 0
        hours_match = re.search(r'(\d+)\s*h', runtime_str)
        if hours_match:
            minutes += int(hours_match.group(1)) * 60
        mins_match = re.search(r'(\d+)\s*m', runtime_str)
        if mins_match:
            minutes += int(mins_match.group(1))
        return minutes

    def top_directors(self, n):
        directors = Counter()
        for record in self.data[:30]:
            raw_id = record.get('imdbId') or record.get('imdbid')
            if not raw_id:
                continue
            imdb_id = 'tt' + str(raw_id).strip().zfill(7)
            movie_data = self.get_movie_info(imdb_id)
            
            # Если API вернул пустую заглушку N/A, пропускаем фильм
            if movie_data and movie_data.get('Director', 'N/A') != 'N/A' and movie_data.get('Title', 'N/A') != 'N/A':
                director_name = movie_data['Director']
                directors[director_name] += 1
        return dict(directors.most_common(n))

    def most_expensive(self, n):
        budgets = {}
        for record in self.data[:30]:
            raw_id = record.get('imdbId') or record.get('imdbid')
            if not raw_id:
                continue
            imdb_id = 'tt' + str(raw_id).strip().zfill(7)
            movie_data = self.get_movie_info(imdb_id)
            if movie_data and movie_data.get('Title', 'N/A') != 'N/A':
                title = movie_data['Title']
                budget_str = movie_data.get('Budget', 'N/A')
                if budget_str != 'N/A':
                    budgets[title] = self.money_to_number(budget_str)
        sorted_items = sorted(budgets.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_items[:n])

    def most_profitable(self, n):
        profits = {}
        for record in self.data[:30]:
            raw_id = record.get('imdbId') or record.get('imdbid')
            if not raw_id:
                continue
            imdb_id = 'tt' + str(raw_id).strip().zfill(7)
            movie_data = self.get_movie_info(imdb_id)
            if movie_data and movie_data.get('Title', 'N/A') != 'N/A':
                title = movie_data['Title']
                gross_str = movie_data.get('Cumulative Worldwide Gross', 'N/A')
                budget_str = movie_data.get('Budget', 'N/A')
                if gross_str != 'N/A' and budget_str != 'N/A':
                    profit = self.money_to_number(gross_str) - self.money_to_number(budget_str)
                    profits[title] = profit
        sorted_items = sorted(profits.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_items[:n])

    def longest(self, n):
        runtimes = {}
        for record in self.data[:30]:
            raw_id = record.get('imdbId') or record.get('imdbid')
            if not raw_id:
                continue
            imdb_id = 'tt' + str(raw_id).strip().zfill(7)
            movie_data = self.get_movie_info(imdb_id)
            if movie_data and movie_data.get('Title', 'N/A') != 'N/A':
                title = movie_data['Title']
                runtime_str = movie_data.get('Runtime', 'N/A')
                if runtime_str != 'N/A':
                    runtime_min = self.runtime_to_minutes(runtime_str)
                    if runtime_min > 0:
                        runtimes[title] = runtime_min
        sorted_items = sorted(runtimes.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_items[:n])

    def top_cost_per_minute(self, n):
        costs = {}
        for record in self.data[:30]:
            raw_id = record.get('imdbId') or record.get('imdbid')
            if not raw_id:
                continue
            imdb_id = 'tt' + str(raw_id).strip().zfill(7)
            movie_data = self.get_movie_info(imdb_id)
            if movie_data and movie_data.get('Title', 'N/A') != 'N/A':
                title = movie_data['Title']
                budget_str = movie_data.get('Budget', 'N/A')
                runtime_str = movie_data.get('Runtime', 'N/A')
                if budget_str != 'N/A' and runtime_str != 'N/A':
                    budget_num = self.money_to_number(budget_str)
                    runtime_min = self.runtime_to_minutes(runtime_str)
                    if budget_num > 0 and runtime_min > 0:
                        costs[title] = round(budget_num / runtime_min, 2)
        sorted_items = sorted(costs.items(), key=lambda x: x[1], reverse=True)
        return dict(sorted_items[:n])


class Tests:
    """Тесты методов класса Links"""
    PATH_LINKS = "../delciefe/links.csv" 

    def test_links_get_imdb(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:3]
        list_of_movies = [int(row['movieId']) for row in links_obj.data]
        list_of_fields = ["Director", "Budget", "Runtime"]
        result = links_obj.get_imdb(list_of_movies, list_of_fields)
        assert isinstance(result, list), "Должен вернуться список"     
        if result:
            assert isinstance(result[0], list), "Элементы списка должны быть списками"
            assert isinstance(result[0][0], int), "Первый элемент строки должен быть movieId (int)"
            movie_ids = [row[0] for row in result]
            assert movie_ids == sorted(movie_ids, reverse=True), "Данные не отсортированы по movieId по убыванию"

    def test_links_top_directors(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:5]
        result = links_obj.top_directors(2)
        assert isinstance(result, dict), "Должен вернуться словарь"
        if result:
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Словарь должен быть отсортирован по убыванию значений"

    def test_links_most_expensive(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:5]
        result = links_obj.most_expensive(2)
        assert isinstance(result, dict), "Должен вернуться словарь"
        if result:
            budgets = list(result.values())
            assert budgets == sorted(budgets, reverse=True), "Бюджеты должны быть отсортированы по убыванию"

    def test_links_most_profitable(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:5]
        result = links_obj.most_profitable(2)
        assert isinstance(result, dict), "Должен вернуться словарь"
        if result:
            profits = list(result.values())
            assert profits == sorted(profits, reverse=True), "Прибыль должна быть отсортирована по убыванию"

    def test_links_longest(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:5]
        result = links_obj.longest(2)
        assert isinstance(result, dict), "Должен вернуться словарь"
        if result:
            runtimes = list(result.values())
            assert runtimes == sorted(runtimes, reverse=True), "Хронометраж должен быть отсортирован по убыванию"

    def test_links_top_cost_per_minute(self):
        links_obj = Links(self.PATH_LINKS)
        links_obj.data = links_obj.data[:5]
        result = links_obj.top_cost_per_minute(2)
        assert isinstance(result, dict), "Должен вернуться словарь"
        if result:
            for cost in result.values():
                assert isinstance(cost, float), "Значение стоимости минуты должно быть float"
                assert cost == round(cost, 2), "Значение должно быть округлено до 2 знаков"
            costs = list(result.values())
            assert costs == sorted(costs, reverse=True), "Значения должны быть отсортированы по убыванию"
    
    """Тесты для класса Movies"""
    PATH_MOVIES = "../latoyiah/movies.csv"

    def test_movies_dist_by_release(self):
        movies_obj = Movies(self.PATH_MOVIES)
        result = movies_obj.dist_by_release()
        assert isinstance(result, dict), "dist_by_release должен возвращать словарь"
        if result:
            for year, count in result.items():
                assert isinstance(year, int), "Ключ (год) должен быть числом"
                assert isinstance(count, int), "Значение (количество) должно быть числом"
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Года не отсортированы по убыванию количества фильмов"

    def test_movies_dist_by_genres(self):
        movies_obj = Movies(self.PATH_MOVIES)
        result = movies_obj.dist_by_genres()
        assert isinstance(result, dict), "dist_by_genres должен возвращать словарь"
        if result:
            for genre, count in result.items():
                assert isinstance(genre, str), "Ключ (жанр) должен быть строкой"
                assert isinstance(count, int), "Значение (количество) должно быть числом"
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Жанры не отсортированы по убыванию популярности"

    def test_movies_most_genres(self):
        movies_obj = Movies(self.PATH_MOVIES)
        n = 10
        result = movies_obj.most_genres(n)
        assert isinstance(result, dict), "most_genres должен возвращать словарь"
        assert len(result) <= n, f"Количество элементов не должно превышать {n}"
        if result:
            for title, count in result.items():
                assert isinstance(title, str), "Ключ (название фильма) должен быть строкой"
                assert isinstance(count, int), "Значение (количество жанров) должно быть числом"
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Фильмы не отсортированы по количеству жанров по убыванию"
    
    PATH_RATINGS = "../latoyiah/ratings.csv"
    PATH_MOVIES = "../latoyiah/movies.csv"

    """Тесты для класса Ratings.Movies"""

    def test_ratings_movies_dist_by_year(self):
        """Тест распределения оценок по годам (сортировка ключей по возрастанию)"""
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        result = ratings_obj.movies.dist_by_year()
        assert isinstance(result, dict), "Метод должен возвращать словарь"
        if result:
            for year, count in result.items():
                assert isinstance(year, int), "Ключ (год) должен быть int"
                assert isinstance(count, int), "Значение (количество) должно быть int"
            years = list(result.keys())
            assert years == sorted(years), "Ключи-года должны быть отсортированы по возрастанию"

    def test_ratings_movies_dist_by_rating(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        result = ratings_obj.movies.dist_by_rating()
        assert isinstance(result, dict)
        if result:
            for rating_value, count in result.items():
                assert isinstance(rating_value, float), "Ключ (оценка) должен быть float"
                assert isinstance(count, int), "Значение (количество) должно быть int"
            ratings = list(result.keys())
            assert ratings == sorted(ratings), "Ключи-оценки должны быть отсортированы по возрастанию"

    def test_ratings_movies_top_by_num_of_ratings(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        top_n = 5
        result = ratings_obj.movies.top_by_num_of_ratings(top_n)
        assert isinstance(result, dict)
        assert len(result) <= top_n, f"Результат не должен превышать {top_n} элементов"
        if result:
            for title, count in result.items():
                assert isinstance(title, str), "Ключ (название фильма) должен быть строкой"
                assert isinstance(count, int), "Значение (количество) должно быть int"
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Значения должны быть отсортированы по убыванию"

    def test_ratings_movies_top_by_ratings(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        top_n = 5
        result_avg = ratings_obj.movies.top_by_ratings(top_n, 'average')
        assert isinstance(result_avg, dict)
        if result_avg:
            for val in result_avg.values():
                assert isinstance(val, (int, float))
                assert val == round(val, 2), "Значение должно быть округлено до 2 знаков"
            scores = list(result_avg.values())
            assert scores == sorted(scores, reverse=True), "Сортировка должна быть по убыванию"
        result_med = ratings_obj.movies.top_by_ratings(top_n, 'median')
        assert isinstance(result_med, dict)

    def test_ratings_movies_top_controversial(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        top_n = 5
        result = ratings_obj.movies.top_controversial(top_n)
        assert isinstance(result, dict)
        assert len(result) <= top_n
        if result:
            for val in result.values():
                assert isinstance(val, (int, float))
                assert val == round(val, 2), "Дисперсия должна быть округлена до 2 знаков"
            variances = list(result.values())
            assert variances == sorted(variances, reverse=True), "Дисперсия должна быть отсортирована по убыванию"


        """Тесты для класса Ratings.Users"""

    def test_ratings_users_dist_by_num_of_ratings(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        result = ratings_obj.users.dist_by_num_of_ratings()
        assert isinstance(result, dict)
        if result:
            for count_key, user_count in result.items():
                assert isinstance(count_key, int)
                assert isinstance(user_count, int)
            keys = list(result.keys())
            assert keys == sorted(keys), "Ключи должны быть отсортированы по возрастанию"

    def test_ratings_users_dist_by_avg_rating(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        result = ratings_obj.users.dist_by_avg_rating('average')
        assert isinstance(result, dict)
        if result:
            for score_key, user_count in result.items():
                assert isinstance(score_key, (int, float))
                assert isinstance(user_count, int)
                assert score_key == round(score_key, 2), "Ключи должны быть округлены до 2 знаков"
            keys = list(result.keys())
            assert keys == sorted(keys), "Ключи-оценки должны быть отсортированы по возрастанию"

    def test_ratings_users_top_controversial_users(self):
        ratings_obj = Ratings(self.PATH_RATINGS, self.PATH_MOVIES)
        top_n = 5
        result = ratings_obj.users.top_controversial_users(top_n)
        assert isinstance(result, dict)
        assert len(result) <= top_n
        if result:
            for user_id, variance in result.items():
                assert isinstance(user_id, int), "Ключ (userId) должен быть целым числом"
                assert isinstance(variance, (int, float))
                assert variance == round(variance, 2), "Дисперсия должна быть округлена до 2 знаков"
            variances = list(result.values())
            assert variances == sorted(variances, reverse=True), "Значения дисперсии должны быть по убыванию"
    
    """Тесты для класса Tags"""
    PATH_TAGS = "../delciefe/tags.csv"

    def test_tags_most_words(self):
        tags_obj = Tags(self.PATH_TAGS)
        n = 5
        result = tags_obj.most_words(n)
        assert isinstance(result, dict), "most_words должен возвращать словарь"
        assert len(result) <= n
        if result:
            for tag, count in result.items():
                assert isinstance(tag, str), "Тег должен быть строкой"
                assert isinstance(count, int), "Количество слов должно быть числом"
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Теги не отсортированы по количеству слов"

    def test_tags_longest(self):
        tags_obj = Tags(self.PATH_TAGS)
        n = 5
        result = tags_obj.longest(n)
        assert isinstance(result, list), "longest должен возвращать список"
        assert len(result) <= n
        assert len(result) == len(set(result)), "В списке результатов есть дубликаты"
        if len(result) > 1:
            lengths = [len(tag) for tag in result]
            assert lengths == sorted(lengths, reverse=True), "Теги не отсортированы по длине"

    def test_tags_most_words_and_longest(self):
        tags_obj = Tags(self.PATH_TAGS)
        n = 10
        result = tags_obj.most_words_and_longest(n)
        assert isinstance(result, list), "Метод должен возвращать список"
        assert len(result) == len(set(result)), "В пересечении не должно быть дубликатов"
        for tag in result:
            assert isinstance(tag, str)

    def test_tags_most_popular(self):
        tags_obj = Tags(self.PATH_TAGS)
        n = 5
        result = tags_obj.most_popular(n)
        assert isinstance(result, dict)
        assert len(result) <= n
        if result:
            counts = list(result.values())
            assert counts == sorted(counts, reverse=True), "Популярность не отсортирована по убыванию"

    def test_tags_tags_with(self):
        tags_obj = Tags(self.PATH_TAGS)
        test_word = "sci-fi"
        result = tags_obj.tags_with(test_word)
        assert isinstance(result, list)
        assert len(result) == len(set(result)), "В результатах поиска найдены дубликаты"
        if result:
            for tag in result:
                assert test_word.lower() in tag.lower(), f"Тег '{tag}' не содержит слово '{test_word}'"
            assert result == sorted(result), "Теги не отсортированы по алфавиту"    