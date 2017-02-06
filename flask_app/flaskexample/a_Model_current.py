from __future__ import absolute_import, division, print_function
import pandas as pd
import numpy as np
import re
import json
import tweepy
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from imdbpie import Imdb
import tmdbsimple as tmdb
import facebook
from sklearn.ensemble import RandomForestClassifier
from sklearn.externals import joblib
import urllib2
from bs4 import BeautifulSoup
from datetime import datetime
from datetime import date

def ModelIt(title = []):

    # load model
    forest = joblib.load("insight_forest_new.pkl")

    #### get movie title info from website
    title = title.strip()

    ## initial movie search
    tmdb.API_KEY = ""
    tmdb_search = tmdb.Search()
    response = tmdb_search.movie(query = title)

    item_check = 0
    if bool(response["results"]):
        tmdb_id = response["results"][0]["id"]
        tmdb_response = tmdb.Movies(str(tmdb_id)).info()
        if tmdb_response["original_title"].lower().strip() == title.lower():
            item_check = 1

    if item_check:

        budget = tmdb_response['budget']
        release_date = tmdb_response['release_date']

        # search IMDB
        imdb = Imdb()
        imdb = Imdb(anonymize = True) # to proxy requests

        current_title_imdb = imdb.search_for_title(title)
        imdb_id = current_title_imdb[0]["imdb_id"]
        imdb_results = imdb.get_title_by_id(imdb_id)
        current_genres = imdb_results.genres
        runtime = imdb_results.runtime
        release_year = imdb_results.year
        poster_url = imdb_results.poster_url

        genres_fixed = []
        for genre in current_genres:
            if genre == "Sci-Fi":
                genres_fixed.append("SciFi")
            else:
                genres_fixed.append(genre)


        #### get facebook features
        def fb_likes(imdb_id):
            url_stem = "https://www.facebook.com/widgets/like.php?width=280&show_faces=1&layout=standard&href=http%3A%2F%2Fwww.imdb.com/title/"
            imdb_url = url = url_stem + str(imdb_id) + "/"
            content = urllib2.urlopen(url).read()
            soup = BeautifulSoup(content, "lxml")
            sentence = soup.find_all(id="u_0_2")[0].span.string # get sentence like: "43K people like this"
            num_likes = sentence.split(" ")[0]
            return num_likes


        likes = fb_likes(imdb_id)
        if "." in likes:
            likes = likes + '00'
        else:
            likes = likes + '000'

        likes = int(re.sub('[K.]', '', likes))

        # setup tweepy api
        tweepy_token = tweepy.OAuthHandler("", "")
        tweepy_token.set_access_token("21915829-", "")
        tweepy_api = tweepy.API(tweepy_token, wait_on_rate_limit = True, wait_on_rate_limit_notify = True)

        #### get twitter features
        def call_twitter_api(title):
            max_tweets = 100
            twitter_query = title
            twitter_results = pd.DataFrame(
                [status._json for status in tweepy.Cursor(
                    tweepy_api.search, q = twitter_query, lang = "en", monitor_rate_limit = True).items(max_tweets)])
            return twitter_results

        def get_twitter_sentiments(twitter_results):

            # get just tweet text
            sentences = twitter_results['text']

            ## sentiment analysis
            twitter_sentiment = pd.DataFrame() # create empty dataframe
            analyzer = SentimentIntensityAnalyzer()
            for sentence in sentences:
                sentiment_analysis = analyzer.polarity_scores(sentence)
                twitter_sentiment = twitter_sentiment.append(sentiment_analysis, ignore_index = True)

            # pop into dataframe
            twitter_sentiment["text"] = twitter_results["text"]
            return pd.DataFrame.mean(twitter_sentiment, axis = 0)

        twitter_results = call_twitter_api(title)
        sentiment_results = get_twitter_sentiments(twitter_results)

        all_genres = ["Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
        "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance",
        "Music", "Family", "Musical", "Thriller"]

        # match current genres to all genres
        indices = []
        for genre in genres_fixed:
            if genre in all_genres:
                indices.append(all_genres.index(genre))

        # turn into dataframe
        movie_data = pd.DataFrame(columns = ["movie_title", "title_year", "release_date", "metascore", "tomatometer", "imdb",
                                             "runtime", "budget", "facebook_likes", "twitter_positive","Action",
                                             "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                                             "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance",
                                             "Music", "Family", "Musical", "Thriller"])




        movie_data = {
            "movie_title": title,
            "title_year": release_year,
            "release_date": release_date,
            "duration": runtime,
            "budget": budget,
            "facebook_likes_per_day": likes,
            "pos": sentiment_results["pos"],

        }

        for genre in all_genres:
            if not genre in genres_fixed:
                movie_data[genre] = 0
            else:
                movie_data[genre] = 1

        current_movie = pd.DataFrame.transpose(pd.DataFrame.from_dict(movie_data, orient = "index"))

        # facebook likes per day
        # IMDBPie version
        date_format = "%Y-%m-%d"
        today = date.today()
        back_then = datetime.strptime(release_date, date_format)
        days_released = (today - back_then.date()).days
        current_movie["facebook_likes_per_month"] = current_movie["facebook_likes_per_day"] / days_released * 30


        current_movie_features = current_movie[["duration", "title_year", "budget", "facebook_likes_per_month", "pos",
                             "Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                             "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance", "Music", "Family",
                             "Musical", "Thriller"]]

        current_prediction = zip(forest.classes_, forest.predict_proba(current_movie_features)[0])

        if current_prediction[0][1] > current_prediction[1][1]:
            result = current_prediction[0][0]
            probability = current_prediction[0][1]
        elif current_prediction[1][1] > current_prediction[0][1]:
            result = current_prediction[1][0]
            probability = current_prediction[1][1]

        if result == "failure":
            message = "The Movie Model is " + str("{0:.2f}".format(probability * 100)) + "%" + " confident that people HATE " + "'" + str(title) + "'" + "."
        else:
            message = "The Movie Model is " + str("{0:.2f}".format(probability * 100)) + "%" " confident that people LOVE " + "'" + str(title) + "'" + "."
            # no movie found

        ## get similar Movies
        # load historical movies
        movie_database = pd.read_csv("movie_database_new.csv")

        ## deal with missing data (results in 1475 rows)
        # replace 0 facebook likes with median
        movie_database.ix[movie_database["facebook_likes_per_month"] == 0, "facebook_likes_per_month"] = movie_database["facebook_likes_per_month"].median()
        movie_database.ix[movie_database["facebook_likes_per_month"].isnull(), "facebook_likes_per_month"] = movie_database["facebook_likes_per_month"].median()

        # replace NAN twitter with median
        movie_database.ix[movie_database["pos"].isnull(), "pos"] = movie_database["pos"].median()

        # replace NAN budget with median
        movie_database.ix[movie_database["budget"].isnull(), "budget"] = movie_database["budget"].median()

        # replace NAN duration with median
        movie_database.ix[movie_database["duration"].isnull(), "duration"] = movie_database["duration"].median()

        # get just movie features
        movie_features = movie_database[["duration", "title_year", "budget", "facebook_likes_per_month", "pos",
                                     "Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                                     "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance", "Music", "Family",
                                     "Musical", "Thriller"]]

        current_movie_genres = current_movie[["Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                             "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance", "Music", "Family",
                             "Musical", "Thriller"]]

        movie_genres = movie_features[["Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                                     "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance", "Music", "Family",
                                     "Musical", "Thriller"]]

        genre_indices = np.where(current_movie_features.iloc[0, 5:] == 1)[0]

        similar_movies = movie_genres.copy(deep = True)
        for genre in genre_indices:
            similar_movies = similar_movies[movie_genres.iloc[:, genre] == current_movie_genres.iloc[0, genre]]

        similar_movies = movie_database.loc[similar_movies.index, :]
        similar_movie_features = similar_movies[["duration", "title_year", "budget", "facebook_likes_per_month", "pos",
                                     "Action", "Adventure", "Animation", "Comedy", "Drama", "Mystery", "Crime",
                                     "Biography", "SciFi", "Horror", "Fantasy", "Documentary", "Romance", "Music", "Family",
                                     "Musical", "Thriller"]]
        similar_movie_features.reset_index();

        # get most similar movies (using dot product)
        dots =  []
        for i in range(0, len(similar_movie_features)):
            dots.append(np.dot(current_movie_features, similar_movie_features.iloc[i]))

        movie_similarity = similar_movie_features.copy(deep = True)
        movie_similarity["dot"] = dots
        movie_similarity["movie_title"] = similar_movies["movie_title"]
        movie_similarity = movie_similarity[~movie_similarity['movie_title'].str.contains(current_movie["movie_title"][0])]
        #movie_similarity = movie_similarity.dropna()
        movie_similarity.sort_values(["dot"], ascending = False, inplace = True)

        top_5_similar = movie_similarity["movie_title"][0:5]

        similar_message = "Similar movies: "
        for similar in top_5_similar:
            similar_message = similar_message + str(similar) + ", "
        similar_message = similar_message[:-2]



    else:
        message = "Movie not found. Is the title spelled correctly?"
        poster_url = " "

    return message, poster_url, similar_message
    #return result, probability, poster_url
