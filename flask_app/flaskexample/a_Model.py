from __future__ import absolute_import, division, print_function
import pandas as pd
import numpy as np
import re
import json
import tweepy
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import omdb
import tmdbsimple as tmdb
#import facebook
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

    #### get movie features
    # search omdb for most movie features
    omdb_result = omdb.get(title = title)
    item_check = 1
    if bool(omdb_result):
        items = [omdb_result.released, omdb_result.year, omdb_result.runtime, omdb_result.poster]
        # kick back movies without features
        # found wrong movie most likely
        for item in items:
            if item == "N/A":
                item_check = 0

    if (bool(omdb_result)) and (item_check):

        release_date = omdb_result.released
        release_year = float(omdb_result.year)
        poster_url = omdb_result.poster
        #tomato_meter = float(omdb_result.tomato_meter)
        #metascore = float(omdb_result.metascore)
        #imdb = float(omdb_result.imdb_rating)
        #content_rating = omdb_result.rated
        #actors = omdb_result.actors
        imdb_id = omdb_result.imdb_id
        #director = omdb_result.director
        #tomato_fresh = omdb_result.tomato_image
        #release_date = omdb_result.released
        runtime = float(re.sub('[^0-9]+', '', omdb_result.runtime))
        #box_office = float(re.sub('[^A-Za-z0-9]+', '', omdb_result.box_office[:-3])) # remove zeros after decimal

        # search tmdb for budget
        tmdb.API_KEY = ''
        tmdb_search = tmdb.Search()
        response = tmdb_search.movie(query = title)
        #imdb_id = tmdb_search.results[0]['id']
        tmdb_response = tmdb.Movies(str(imdb_id)).info()
        budget = tmdb_response['budget']

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
        tweepy_token.set_access_token("", "")
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

        # turn into dataframe
        movie_data = pd.DataFrame(columns = ["movie_title", "title_year", "metascore", "tomatometer", "imdb",
                                             "runtime", "budget", "facebook_likes", "twitter_positive"])

        movie_data = {
            "movie_title": title,
            "title_year": release_year,
            #"metascore": metascore,
            #"tomatometer": tomato_meter,
            #"imdb": imdb,
            #"content_rating": content_rating,
            "duration": runtime,
            "budget": budget,
            "facebook_likes_per_day": likes,
            #"twitter_neutral": sentiment_results["neu"],
            "pos": sentiment_results["pos"],
            #"twitter_negative": sentiment_results["neg"],
            #"twtter_compound": sentiment_results["compound"]

        }

        current_movie = pd.DataFrame.transpose(pd.DataFrame.from_dict(movie_data, orient = "index"))

        # facebook likes per day
        date_format = "%d %b %Y"
        today = date.today()
        back_then = datetime.strptime(release_date, date_format)
        current_movie["facebook_likes_per_day"] = (today - back_then.date()).days

        current_movie = pd.DataFrame.transpose(pd.DataFrame.from_dict(movie_data, orient = "index"))

        current_movie_features = current_movie[["duration", "title_year", "budget", "facebook_likes_per_day", "pos"]]

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
    else:
        message = "Movie not found. Is the title spelled correctly?"
        poster_url = " "

    return message, poster_url
    #return result, probability, poster_url
