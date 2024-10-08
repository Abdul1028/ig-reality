import json
import codecs
import os.path
import datetime
import sys
import urllib
import os
from logging import fatal
from pathlib import Path
import requests
import ssl
import nltk
ssl._create_default_https_context = ssl._create_unverified_context

from instagram_private_api import ClientCookieExpiredError, ClientLoginRequiredError, ClientError, ClientThrottledError
from instagram_private_api import Client as AppClient
from geopy.geocoders import Nominatim
import pandas as pd
import streamlit as st
from instagram_private_api import (
    Client, ClientError, ClientLoginError,
    ClientCookieExpiredError, ClientLoginRequiredError,
    __version__ as client_version
)
from prettytable import PrettyTable


# Helper functions for JSON serialization/deserialization
def to_json(python_object):
    if isinstance(python_object, bytes):
        return {'__class__': 'bytes',
                '__value__': codecs.encode(python_object, 'base64').decode()}
    raise TypeError(repr(python_object) + ' is not JSON serializable')


def from_json(json_object):
    if '__class__' in json_object and json_object['__class__'] == 'bytes':
        return codecs.decode(json_object['__value__'].encode(), 'base64')
    return json_object

import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

nltk.download('vader_lexicon')
nltk.download('punkt')


class InstagramHelper:
    api = None
    target = ""
    user_id = None
    target_id = None
    is_private = True
    following = False
    geolocator = Nominatim(user_agent="http")
    output_dir = "output"



    def __init__(self, target, output_dir, username,password,is_file=None, is_json=None):
        self.output_dir = output_dir or self.output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self.login(username,password)
        self.setTarget(target)
        st.toast(target)
        self.writeFile = is_file
        self.jsonDump = is_json
    def login(self, username, password):
        try:
            # Initialize the Instagram API client
            device_id = None
            settings_file = 'settings.json'  # Change this to your desired file name

            if not os.path.isfile(settings_file):
                # Settings file does not exist, perform a new login
                self.api = Client(
                    username, password,
                    on_login=lambda x: self.onlogin_callback(x, settings_file))
            else:
                # Reuse cached settings
                with open(settings_file) as file_data:
                    cached_settings = json.load(file_data, object_hook=from_json)
                device_id = cached_settings.get('device_id')
                self.api = Client(username, password, settings=cached_settings)
                st.toast("Logged in succesfully!")

            return self.api  # Return the API object if login is successful


        except ClientLoginError as e:
            raise Exception('Invalid username or password. Please try again.')
        except Exception as e:
            raise Exception(f'Unexpected Exception: {e}')

    def onlogin_callback(self, api, new_settings_file):
        cache_settings = api.settings
        with open(new_settings_file, 'w') as outfile:
            json.dump(cache_settings, outfile, default=to_json)

    def check_following(self):
        if str(self.target_id) == self.api.authenticated_user_id:
            return True
        response = self.api.friendships_show(self.target_id)
        if response['following']:
            return True
        else:
            return False



    def is_follows(self):
        response = self.api.friendships_show(self.target_id)
        if response['following']:
            return "Follows you"
        else:
            return "Not follows you"


    def setTarget(self, target):
        self.target = target
        user = self.get_user(target)
        self.target_id = user['id']
        self.is_private = user['is_private']
        if user['is_private']:
            st.toast("Profile is private")
        self.following = self.check_following()



    def change_target(self,new_target):
        print("Insert new target username: ")
        self.setTarget(new_target)
        return



    def __get_feed__(self):
        data = []

        result = self.api.user_feed(str(self.target_id))
        data.extend(result.get('items', []))


        next_max_id = result.get('next_max_id')
        while next_max_id:
            results = self.api.user_feed(str(self.target_id), max_id=next_max_id)
            data.extend(results.get('items', []))
            next_max_id = results.get('next_max_id')

        return data

    def __get_comments__(self, media_id):
        comments = []

        result = self.api.media_comments(str(media_id))
        comments.extend(result.get('comments', []))

        next_max_id = result.get('next_max_id')
        while next_max_id:
            results = self.api.media_comments(str(media_id), max_id=next_max_id)
            comments.extend(results.get('comments', []))
            next_max_id = results.get('next_max_id')

        return comments

    def get_addrs(self):
        st.write("Searching for target localizations...\n")

        # Replace this with your actual data retrieval logic
        data = self.__get_feed__()

        locations = {}

        for post in data:
            if 'location' in post and post['location'] is not None:
                if 'lat' in post['location'] and 'lng' in post['location']:
                    lat = post['location']['lat']
                    lng = post['location']['lng']
                    locations[str(lat) + ', ' + str(lng)] = post.get('taken_at')

        st.write(locations)
        address = {}
        for k, v in locations.items():
            details = self.geolocator.reverse(k)
            unix_timestamp = datetime.datetime.fromtimestamp(v)
            address[details.address] = unix_timestamp.strftime('%Y-%m-%d %H:%M:%S')

        sort_addresses = sorted(address.items(), key=lambda p: p[1], reverse=True)

        if len(sort_addresses) > 0:
            # Create a Pandas DataFrame from the sorted addresses
            df = pd.DataFrame(sort_addresses, columns=['Address', 'Time'])

            # Display the DataFrame as a table
            st.dataframe(df,use_container_width=True,hide_index=True)

        else:
            st.write("Sorry! No results found :-(\n")

    def get_captions(self):
        if self.check_private_profile():
            return

        st.write("Searching for target captions...\n")

        captions = []

        data = self.__get_feed__()
        counter = 0

        try:
            for item in data:
                if "caption" in item:
                    if item["caption"] is not None:
                        text = item["caption"]["text"]
                        captions.append(text)
                        counter = counter + 1
                        st.write("Found: ",counter)

        except AttributeError:
            pass

        except KeyError:
            pass

        json_data = {}

        if counter > 0:
            st.write("\nWoohoo! We found " + str(counter) + " captions\n" )

            file = None

            if self.writeFile:
                file_name = self.output_dir + "/" + self.target + "_captions.txt"
                file = open(file_name, "w")

            for s in captions:
                st.write(s + "\n")

            #     if self.writeFile:
            #         file.write(s + "\n")
            #
            # if self.jsonDump:
            #     json_data['captions'] = captions
            #     json_file_name = self.output_dir + "/" + self.target + "_followings.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)
            #
            # if file is not None:
            #     file.close()

        else:
            st.write("Sorry! No results found :-(\n"  )

        return

    def get_total_comments(self):
        if self.check_private_profile():
            return

        st.write("Searching for target total comments...\n")

        comments_counter = 0
        posts = 0

        data = self.__get_feed__()

        for post in data:
            comments_counter += post['comment_count']
            posts += 1

        # if self.writeFile:
        #     file_name = self.output_dir + "/" + self.target + "_comments.txt"
        #     file = open(file_name, "w")
        #     file.write(str(comments_counter) + " comments in " + str(posts) + " posts\n")
        #     file.close()
        #
        # if self.jsonDump:
        #     json_data = {
        #         'comment_counter': comments_counter,
        #         'posts': posts
        #     }
        #     json_file_name = self.output_dir + "/" + self.target + "_comments.json"
        #     with open(json_file_name, 'w') as f:
        #         json.dump(json_data, f)

        st.write(str(comments_counter)   )
        st.write(" comments in " + str(posts) + " posts\n")

    # def get_comment_data(self):
    #     if self.check_private_profile():
    #         return
    #
    #     st.write("Retrieving all comments, this may take a moment...\n")
    #     data = self.__get_feed__()
    #
    #     _comments = []
    #     t = PrettyTable(['POST ID', 'ID', 'Username', 'Comment'])
    #     t.align["POST ID"] = "l"
    #     t.align["ID"] = "l"
    #     t.align["Username"] = "l"
    #     t.align["Comment"] = "l"
    #
    #     for post in data:
    #         post_id = post.get('id')
    #         comments = self.api.media_n_comments(post_id)
    #         for comment in comments:
    #             t.add_row([post_id, comment.get('user_id'), comment.get('user').get('username'), comment.get('text')])
    #             comment = {
    #                 "post_id": post_id,
    #                 "user_id": comment.get('user_id'),
    #                 "username": comment.get('user').get('username'),
    #                 "comment": comment.get('text')
    #             }
    #             _comments.append(comment)
    #
    #     st.write(t)
    #     # if self.writeFile:
    #     #     file_name = self.output_dir + "/" + self.target + "_comment_data.txt"
    #     #     with open(file_name, 'w') as f:
    #     #         f.write(str(t))
    #     #         f.close()
    #     #
    #     # if self.jsonDump:
    #     #     file_name_json = self.output_dir + "/" + self.target + "_comment_data.json"
    #     #     with open(file_name_json, 'w') as f:
    #     #         f.write("{ \"Comments\":[ \n")
    #     #         f.write('\n'.join(json.dumps(comment) for comment in _comments) + ',\n')
    #     #         f.write("]} ")


    def get_comment_data(self):
        if self.check_private_profile():
            return

        st.write("Retrieving all comments, this may take a moment...\n")
        data = self.__get_feed__()

        _comments = []

        # Prepare to collect comment data
        for post in data:
            post_id = post.get('id')
            comments = self.api.media_n_comments(post_id)
            for comment in comments:
                comment_info = {
                    "username": comment.get('user').get('username'),
                    "comment": comment.get('text'),
                    "post_id": post_id,
                    "user_id": comment.get('user_id'),
                }
                _comments.append(comment_info)  # Store comment info in the list

        if _comments:
            # Create a DataFrame to hold the comment data
            df = pd.DataFrame(_comments)

            # Display the DataFrame as a table in Streamlit
            st.dataframe(df,use_container_width=True,hide_index=True)  # Use st.dataframe(df) for an interactive table
        else:
            st.write("No comments found for any posts.\n")

    def get_followers(self):
        if self.check_private_profile():
            return

        st.write("Searching for target followers...\n")

        _followers = []
        followers = []

        rank_token = AppClient.generate_uuid()
        data = self.api.user_followers(str(self.target_id), rank_token=rank_token)

        _followers.extend(data.get('users', []))

        next_max_id = data.get('next_max_id')
        while next_max_id:
            sys.stdout.write("\rCatched %i followers" % len(_followers))
            sys.stdout.flush()
            results = self.api.user_followers(str(self.target_id), rank_token=rank_token, max_id=next_max_id)
            _followers.extend(results.get('users', []))
            next_max_id = results.get('next_max_id')

        print("\n")

        for user in _followers:
            u = {
                'username': user['username'],
                'full_name': user['full_name'],
                'id': user['pk'],
            }
            followers.append(u)

        # Create a DataFrame from the followers list
        df_followers = pd.DataFrame(followers)

        # Display the DataFrame as a table in Streamlit
        st.write("### Followers")
        st.write(f'Total {len(followers)} followings found')
        st.dataframe(df_followers, use_container_width=True,hide_index=True)

        # Uncomment the following lines if you want to write to file or json
        # if self.writeFile:
        #     file_name = self.output_dir + "/" + self.target + "_followers.txt"
        #     with open(file_name, "w") as file:
        #         file.write(str(df_followers))
        #
        # if self.jsonDump:
        #     json_data = {'followers': followers}
        #     json_file_name = self.output_dir + "/" + self.target + "_followers.json"
        #     with open(json_file_name, 'w') as f:
        #         json.dump(json_data, f)

    def get_followings(self):
        if self.check_private_profile():
            return

        st.write("Searching for target followings...\n")

        _followings = []
        followings = []

        rank_token = AppClient.generate_uuid()
        data = self.api.user_following(str(self.target_id), rank_token=rank_token)

        _followings.extend(data.get('users', []))

        next_max_id = data.get('next_max_id')
        while next_max_id:
            sys.stdout.write("\rCatched %i followings" % len(_followings))
            sys.stdout.flush()
            results = self.api.user_following(str(self.target_id), rank_token=rank_token, max_id=next_max_id)
            _followings.extend(results.get('users', []))
            next_max_id = results.get('next_max_id')

        print("\n")

        for user in _followings:
            u = {
                'username': user['username'],
                'full_name': user['full_name'],
                'id': user['pk'],
            }
            followings.append(u)

        # Create a DataFrame from the followings list
        df_followings = pd.DataFrame(followings)

        # Display the DataFrame as a table in Streamlit
        st.write("### Followings")
        st.write(f'Total {len(followings)} followings found')
        st.dataframe(df_followings, use_container_width=True,hide_index=True)

        # Uncomment the following lines if you want to write to file or json
        # if self.writeFile:
        #     file_name = self.output_dir + "/" + self.target + "_followings.txt"
        #     with open(file_name, "w") as file:
        #         file.write(str(df_followings))
        #
        # if self.jsonDump:
        #     json_data = {'followings': followings}
        #     json_file_name = self.output_dir + "/" + self.target + "_followings.json"
        #     with open(json_file_name, 'w') as f:
        #         json.dump(json_data, f)


    def get_hashtags(self):
        if self.check_private_profile():
            return

        st.write("Searching for target hashtags...\n")

        hashtags = []
        texts = []

        data = self.api.user_feed(str(self.target_id))
        texts.extend(data.get('items', []))

        next_max_id = data.get('next_max_id')
        while next_max_id:
            results = self.api.user_feed(str(self.target_id), max_id=next_max_id)
            texts.extend(results.get('items', []))
            next_max_id = results.get('next_max_id')

        for post in texts:
            if post['caption'] is not None:
                caption = post['caption']['text']
                for s in caption.split():
                    if s.startswith('#'):
                        hashtags.append(s.encode('UTF-8'))

        if len(hashtags) > 0:
            hashtag_counter = {}

            for i in hashtags:
                if i in hashtag_counter:
                    hashtag_counter[i] += 1
                else:
                    hashtag_counter[i] = 1

            # Sort hashtags based on their counts
            ssort = sorted(hashtag_counter.items(), key=lambda value: value[1], reverse=True)

            # Prepare data for the DataFrame
            data_dict = {
                'Hashtag': [str(k.decode('utf-8')) for k, v in ssort],
                'Count': [v for k, v in ssort]
            }
            df = pd.DataFrame(data_dict)

            # Display the DataFrame as a table in Streamlit
            st.dataframe(df, use_container_width=True,hide_index=True)  # Use st.dataframe for an interactive table

        else:
            st.write("Sorry! No results found :-(\n")

    def get_user_info(self):
        try:
            # Fetch the user's info

            user_info = self.api.username_info(self.target)
            # Display user information
            st.subheader('User Information')
            st.write(user_info)
            st.write(f"User ID: {user_info['user']['pk']}")

            st.write(f"Username: {user_info['user']['username']}")
            st.write(f"Full Name: {user_info['user']['full_name']}")
            st.write(f"Bio: {user_info['user']['biography']}")
            st.write(f"Followers: {user_info['user']['follower_count']}")
            st.write(f"Following: {user_info['user']['following_count']}")
            st.write(f"Posts: {user_info['user']['media_count']}")
            st.write(f"Private: {user_info['user']['is_private']}")

            return user_info
        

        except ClientError as e:
            print('Error')
            print(f'Client Error: {e}')

    def get_total_likes(self):
        if self.check_private_profile():
            return

        st.write("Searching for target total likes...\n")

        like_counter = 0
        posts = 0

        data = self.__get_feed__()

        for post in data:
            like_counter += post['like_count']
            posts += 1

        # if self.writeFile:
        #     file_name = self.output_dir + "/" + self.target + "_likes.txt"
        #     file = open(file_name, "w")
        #     file.write(str(like_counter) + " likes in " + str(like_counter) + " posts\n")
        #     file.close()
        #
        # if self.jsonDump:
        #     json_data = {
        #         'like_counter': like_counter,
        #         'posts': like_counter
        #     }
        #     json_file_name = self.output_dir + "/" + self.target + "_likes.json"
        #     with open(json_file_name, 'w') as f:
        #         json.dump(json_data, f)

        st.write(str(like_counter)   )
        st.write(" likes in " + str(posts) + " posts\n")

    def get_media_type(self):
        if self.check_private_profile():
            return

        st.write("Searching for target captions...\n")

        counter = 0
        photo_counter = 0
        video_counter = 0

        data = self.__get_feed__()

        for post in data:
            if "media_type" in post:
                if post["media_type"] == 1:
                    photo_counter = photo_counter + 1
                elif post["media_type"] == 2:
                    video_counter = video_counter + 1
                counter = counter + 1
                sys.stdout.write("\rChecked %i" % counter)
                sys.stdout.flush()

        sys.stdout.write(" posts")
        sys.stdout.flush()

        if counter > 0:
            pass

            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_mediatype.txt"
            #     file = open(file_name, "w")
            #     file.write(str(photo_counter) + " photos and " + str(video_counter) + " video posted by target\n")
            #     file.close()
            #
            # print("\nWoohoo! We found " + str(photo_counter) + " photos and " + str(video_counter) +
            #             " video posted by target\n" )
            #
            # if self.jsonDump:
            #     json_data = {
            #         "photos": photo_counter,
            #         "videos": video_counter
            #     }
            #     json_file_name = self.output_dir + "/" + self.target + "_mediatype.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)


        else:
            st.write("Sorry! No results found :-(\n"  )

    import streamlit as st
    import pandas as pd

    def get_people_who_commented(self):
        if self.check_private_profile():
            return

        st.write("Searching for users who commented...\n")

        data = self.__get_feed__()
        users = []

        for post in data:
            comments = self.__get_comments__(post['id'])
            for comment in comments:
                # Check if the user is already in the list
                if not any(u['id'] == comment['user']['pk'] for u in users):
                    user = {
                        'id': comment['user']['pk'],
                        'username': comment['user']['username'],
                        'full_name': comment['user']['full_name'],
                        'counter': 1
                    }
                    users.append(user)
                else:
                    for user in users:
                        if user['id'] == comment['user']['pk']:
                            user['counter'] += 1
                            break

        if len(users) > 0:
            # Sort users based on the number of comments
            ssort = sorted(users, key=lambda value: value['counter'], reverse=True)

            # Create a DataFrame to hold the user data
            data_dict = {
                'Comments': [str(u['counter']) for u in ssort],
                'ID': [u['id'] for u in ssort],
                'Username': [u['username'] for u in ssort],
                'Full Name': [u['full_name'] for u in ssort]
            }
            df = pd.DataFrame(data_dict)

            # Display the DataFrame as a table in Streamlit without the index
            st.dataframe(df, use_container_width=True,hide_index=True)  # Use st.dataframe for an interactive table

        else:
            st.write("Sorry! No results found :-(\n")

    import streamlit as st
    import pandas as pd

    def get_people_who_tagged(self):
        if self.check_private_profile():
            return

        st.write("Searching for users who tagged target...\n")

        posts = []

        result = self.api.usertag_feed(self.target_id)
        posts.extend(result.get('items', []))

        next_max_id = result.get('next_max_id')
        while next_max_id:
            results = self.api.user_feed(str(self.target_id), max_id=next_max_id)
            posts.extend(results.get('items', []))
            next_max_id = results.get('next_max_id')

        if len(posts) > 0:
            st.write("\nWoohoo! We found " + str(len(posts)) + " photos\n")

            users = []

            for post in posts:
                if not any(u['id'] == post['user']['pk'] for u in users):
                    user = {
                        'id': post['user']['pk'],
                        'username': post['user']['username'],
                        'full_name': post['user']['full_name'],
                        'counter': 1
                    }
                    users.append(user)
                else:
                    for user in users:
                        if user['id'] == post['user']['pk']:
                            user['counter'] += 1
                            break

            # Sort users by the number of photos tagged
            ssort = sorted(users, key=lambda value: value['counter'], reverse=True)

            # Create a DataFrame from the sorted user list
            df_users = pd.DataFrame(ssort)

            # Display the DataFrame as a table in Streamlit
            st.write("### Users Who Tagged Target")
            st.dataframe(df_users[['username', 'full_name','counter', 'id', ]], use_container_width=True,hide_index=True)

            # Uncomment the following lines if you want to write to file or json
            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_users_who_tagged.txt"
            #     with open(file_name, "w") as file:
            #         file.write(str(df_users))
            #
            # if self.jsonDump:
            #     json_data['users_who_tagged'] = ssort
            #     json_file_name = self.output_dir + "/" + self.target + "_users_who_tagged.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)
        else:
            st.write("Sorry! No results found :-(\n")

    def get_photo_description(self):
        if self.check_private_profile():
            return

        content = requests.get("https://www.instagram.com/" + str(self.target) + "/?__a=1")
        data = content.json()

        dd = data['graphql']['user']['edge_owner_to_timeline_media']['edges']

        if len(dd) > 0:
            st.write("\nWoohoo! We found " + str(len(dd)) + " descriptions\n" )

            count = 1

            t = PrettyTable(['Photo', 'Description'])
            t.align["Photo"] = "l"
            t.align["Description"] = "l"

            json_data = {}
            descriptions_list = []

            for i in dd:
                node = i.get('node')
                descr = node.get('accessibility_caption')
                t.add_row([str(count), descr])

                # if self.jsonDump:
                #     description = {
                #         'description': descr
                #     }
                #     descriptions_list.append(description)
                #
                # count += 1

            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_photodes.txt"
            #     file = open(file_name, "w")
            #     file.write(str(t))
            #     file.close()
            #
            # if self.jsonDump:
            #     json_data['descriptions'] = descriptions_list
            #     json_file_name = self.output_dir + "/" + self.target + "_descriptions.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)

            st.write(t)
        else:
            st.write("Sorry! No results found :-(\n"  )

    def get_user_photo(self,no_of_photos):
        if self.check_private_profile():
            return

        limit = -1
        st.write("How many photos you want to download (default all): ")
        user_input = no_of_photos

        try:
            if user_input == "All":
                st.write("Downloading all photos available...\n")
            else:
                limit = int(user_input)
                st.write("Downloading " + user_input + " photos...\n")

        except ValueError:
            print("Wrong value entered\n"  )
            return

        data = []
        counter = 0

        result = self.api.user_feed(str(self.target_id))
        data.extend(result.get('items', []))

        next_max_id = result.get('next_max_id')
        while next_max_id:
            results = self.api.user_feed(str(self.target_id), max_id=next_max_id)
            data.extend(results.get('items', []))
            next_max_id = results.get('next_max_id')

        try:
            for item in data:
                if counter == limit:
                    break
                if "image_versions2" in item:
                    counter = counter + 1
                    url = item["image_versions2"]["candidates"][0]["url"]
                    photo_id = item["id"]
                    end = self.output_dir + "/" + self.target + "_" + photo_id + ".jpg"
                    urllib.request.urlretrieve(url, end)
                    sys.stdout.write("\rDownloaded %i" % counter)
                    sys.stdout.flush()
                else:
                    carousel = item["carousel_media"]
                    for i in carousel:
                        if counter == limit:
                            break
                        counter = counter + 1
                        url = i["image_versions2"]["candidates"][0]["url"]
                        photo_id = i["id"]
                        end = self.output_dir + "/" + self.target + "_" + photo_id + ".jpg"
                        urllib.request.urlretrieve(url, end)
                        sys.stdout.write("\rDownloaded %i" % counter)
                        sys.stdout.flush()

        except AttributeError:
            pass

        except KeyError:
            pass

        sys.stdout.write(" photos")
        sys.stdout.flush()

        st.write("\nWoohoo! We downloaded " + str(counter) + " photos (saved in " + self.output_dir + " folder) \n")

    def get_user_propic(self):

        try:
            endpoint = 'users/{user_id!s}/full_detail_info/'.format(**{'user_id': self.target_id})
            content = self.api._call_api(endpoint)

            data = content['user_detail']['user']

            if "hd_profile_pic_url_info" in data:
                URL = data["hd_profile_pic_url_info"]['url']
            else:
                # get better quality photo
                items = len(data['hd_profile_pic_versions'])
                URL = data["hd_profile_pic_versions"][items - 1]['url']

            if URL != "":
                end = self.output_dir + "/" + self.target + "_propic.jpg"
                urllib.request.urlretrieve(URL, end)
                st.write("Target propic saved in output folder\n" )

            else:
                st.write("Sorry! No results found :-(\n"  )

        except ClientError as e:
            error = json.loads(e.error_response)
            st.write(error['message'])
            st.write(error['error_title'])

    def get_user_stories(self):
        if self.check_private_profile():
            return

        st.write("Searching for target stories...\n")

        data = self.api.user_reel_media(str(self.target_id))

        counter = 0

        if data['items'] is not None:  # no stories avaibile
            counter = data['media_count']
            for i in data['items']:
                story_id = i["id"]
                if i["media_type"] == 1:  # it's a photo
                    url = i['image_versions2']['candidates'][0]['url']
                    end = self.output_dir + "/" + self.target + "_" + story_id + ".jpg"
                    urllib.request.urlretrieve(url, end)

                elif i["media_type"] == 2:  # it's a gif or video
                    url = i['video_versions'][0]['url']
                    end = self.output_dir + "/" + self.target + "_" + story_id + ".mp4"
                    urllib.request.urlretrieve(url, end)

        if counter > 0:
            st.write(str(counter) + " target stories saved in output folder\n" )
        else:
            st.write("Sorry! No results found :-(\n"  )

    def get_people_tagged_by_user(self):
        st.write("Searching for users tagged by target...\n")

        ids = []
        username = []
        full_name = []
        post = []
        counter = 1

        data = self.__get_feed__()

        try:
            for i in data:
                if "usertags" in i:
                    c = i.get('usertags').get('in')
                    for cc in c:
                        if cc.get('user').get('pk') not in ids:
                            ids.append(cc.get('user').get('pk'))
                            username.append(cc.get('user').get('username'))
                            full_name.append(cc.get('user').get('full_name'))
                            post.append(1)
                        else:
                            index = ids.index(cc.get('user').get('pk'))
                            post[index] += 1
                        counter += 1
        except AttributeError as ae:
            st.write("\nERROR: an error occurred: ")
            st.write(ae)
            st.write("")
            return  # Exit if there's an error

        if len(ids) > 0:
            st.write("\nWoohoo! We found " + str(len(ids)) + " (" + str(counter) + ") users\n")

            # Create a DataFrame to hold the data
            data_dict = {
                'Posts': post,
                'Full Name': full_name,
                'Username': username,
                'ID': ids
            }
            df = pd.DataFrame(data_dict)

            # Display the DataFrame as a table in Streamlit
            st.dataframe(df,use_container_width=True,hide_index=True)
        else:
            st.write("Sorry! No results found :-(\n")

    def get_user(self, username):
        try:
            content = self.api.username_info(username)
            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_user_id.txt"
            #     file = open(file_name, "w")
            #     file.write(str(content['user']['pk']))
            #     file.close()

            user = dict()
            user['id'] = content['user']['pk']
            user['is_private'] = content['user']['is_private']

            return user

        except ClientError as e:
            print('ClientError {0!s} (Code: {1:d}, Response: {2!s})'.format(e.msg, e.code, e.error_response))
            error = json.loads(e.error_response)
            if 'message' in error:
                print(error['message'])
            if 'error_title' in error:
                print(error['error_title'])
            if 'challenge' in error:
                print("Please follow this link to complete the challenge: " + error['challenge']['url'])
            sys.exit(2)
            
    def set_write_file(self, flag):
        if flag:
            print("Write to file: ")
            print("enabled" )
            print("\n")
        else:
            print("Write to file: ")
            print("disabled"  )
            print("\n")

        self.writeFile = flag

    def set_json_dump(self, flag):
        if flag:
            print("Export to JSON: ")
            print("enabled" )
            print("\n")
        else:
            print("Export to JSON: ")
            print("disabled"  )
            print("\n")

        self.jsonDump = flag

    def check_private_profile(self):
        if self.is_private and not self.following:
            print("Impossible to execute command: user has private profile\n"  )
            send = input("Do you want send a follow request? [Y/N]: ")
            if send.lower() == "y":
                self.api.friendships_create(self.target_id)
                print("Sent a follow request to target. Use this command after target accepting the request.")

            return True
        return False

    def get_fwersemail(self):
        if self.check_private_profile():
            return

        followers = []

        try:

            st.write("Searching for emails of target followers... this can take a few minutes\n")

            rank_token = AppClient.generate_uuid()
            data = self.api.user_followers(str(self.target_id), rank_token=rank_token)

            for user in data.get('users', []):
                u = {
                    'id': user['pk'],
                    'username': user['username'],
                    'full_name': user['full_name']
                }
                followers.append(u)

            next_max_id = data.get('next_max_id')
            while next_max_id:
                sys.stdout.write("\rCatched %i followers email" % len(followers))
                sys.stdout.flush()
                results = self.api.user_followers(str(self.target_id), rank_token=rank_token, max_id=next_max_id)

                for user in results.get('users', []):
                    u = {
                        'id': user['pk'],
                        'username': user['username'],
                        'full_name': user['full_name']
                    }
                    followers.append(u)

                next_max_id = results.get('next_max_id')

            st.write("\n")

            results = []

            print("Do you want to get all emails? y/n: " )
            value = len(followers)


            for follow in followers:
                user = self.api.user_info(str(follow['id']))
                if 'public_email' in user['user'] and user['user']['public_email']:
                    follow['email'] = user['user']['public_email']
                    if len(results) > value:
                        break
                    results.append(follow)

        except ClientThrottledError as e:
            st.write("\nError: Instagram blocked the requests. Please wait a few minutes before you try again.")
            print("\n")

        if len(results) > 0:

            t = PrettyTable(['ID', 'Username', 'Full Name', 'Email'])
            t.align["ID"] = "l"
            t.align["Username"] = "l"
            t.align["Full Name"] = "l"
            t.align["Email"] = "l"

            json_data = {}

            for node in results:
                t.add_row([str(node['id']), node['username'], node['full_name'], node['email']])

            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_fwersemail.txt"
            #     file = open(file_name, "w")
            #     file.write(str(t))
            #     file.close()
            #
            # if self.jsonDump:
            #     json_data['followers_email'] = results
            #     json_file_name = self.output_dir + "/" + self.target + "_fwersemail.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)

            st.write(t)
        else:
            st.write("Sorry! No results found :-(\n"  )

    def get_fwingsemail(self):
        if self.check_private_profile():
            return

        followings = []

        try:

            st.write("Searching for emails of users followed by target... this can take a few minutes\n")

            rank_token = AppClient.generate_uuid()
            data = self.api.user_following(str(self.target_id), rank_token=rank_token)

            for user in data.get('users', []):
                u = {
                    'id': user['pk'],
                    'username': user['username'],
                    'full_name': user['full_name']
                }
                followings.append(u)

            next_max_id = data.get('next_max_id')

            while next_max_id:
                results = self.api.user_following(str(self.target_id), rank_token=rank_token, max_id=next_max_id)

                for user in results.get('users', []):
                    u = {
                        'id': user['pk'],
                        'username': user['username'],
                        'full_name': user['full_name']
                    }
                    followings.append(u)

                next_max_id = results.get('next_max_id')

            results = []

            print("Do you want to get all emails? y/n: " )
            value = len(followings)


            for follow in followings:
                sys.stdout.write("\rCatched %i followings email" % len(results))
                sys.stdout.flush()
                user = self.api.user_info(str(follow['id']))
                if 'public_email' in user['user'] and user['user']['public_email']:
                    follow['email'] = user['user']['public_email']
                    if len(results) > value:
                        break
                    results.append(follow)

        except ClientThrottledError as e:
            st.write("\nError: Instagram blocked the requests. Please wait a few minutes before you try again.")
            print("\n")

        print("\n")

        if len(results) > 0:
            t = PrettyTable(['ID', 'Username', 'Full Name', 'Email'])
            t.align["ID"] = "l"
            t.align["Username"] = "l"
            t.align["Full Name"] = "l"
            t.align["Email"] = "l"

            json_data = {}

            for node in results:
                t.add_row([str(node['id']), node['username'], node['full_name'], node['email']])
            #
            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_fwingsemail.txt"
            #     file = open(file_name, "w")
            #     file.write(str(t))
            #     file.close()
            #
            # if self.jsonDump:
            #     json_data['followings_email'] = results
            #     json_file_name = self.output_dir + "/" + self.target + "_fwingsemail.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)

            st.write(t)
        else:
            st.write("Sorry! No results found :-(\n"  )

    def get_fwingsnumber(self):
        if self.check_private_profile():
            return

        try:

            st.write("Searching for phone numbers of users followed by target... this can take a few minutes\n")

            followings = []

            rank_token = AppClient.generate_uuid()
            data = self.api.user_following(str(self.target_id), rank_token=rank_token)

            for user in data.get('users', []):
                u = {
                    'id': user['pk'],
                    'username': user['username'],
                    'full_name': user['full_name']
                }
                followings.append(u)

            next_max_id = data.get('next_max_id')

            while next_max_id:
                results = self.api.user_following(str(self.target_id), rank_token=rank_token, max_id=next_max_id)

                for user in results.get('users', []):
                    u = {
                        'id': user['pk'],
                        'username': user['username'],
                        'full_name': user['full_name']
                    }
                    followings.append(u)

                next_max_id = results.get('next_max_id')

            results = []

            print("Do you want to get all phone numbers? y/n: " )
            value = len(followings)

            for follow in followings:
                sys.stdout.write("\rCatched %i followings phone numbers" % len(results))
                sys.stdout.flush()
                user = self.api.user_info(str(follow['id']))
                if 'contact_phone_number' in user['user'] and user['user']['contact_phone_number']:
                    follow['contact_phone_number'] = user['user']['contact_phone_number']
                    if len(results) > value:
                        break
                    results.append(follow)

        except ClientThrottledError as e:
            st.write("\nError: Instagram blocked the requests. Please wait a few minutes before you try again.")
            print("\n")

        print("\n")

        if len(results) > 0:
            t = PrettyTable(['ID', 'Username', 'Full Name', 'Phone'])
            t.align["ID"] = "l"
            t.align["Username"] = "l"
            t.align["Full Name"] = "l"
            t.align["Phone number"] = "l"

            json_data = {}

            for node in results:
                t.add_row([str(node['id']), node['username'], node['full_name'], node['contact_phone_number']])

            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_fwingsnumber.txt"
            #     file = open(file_name, "w")
            #     file.write(str(t))
            #     file.close()
            #
            # if self.jsonDump:
            #     json_data['followings_phone_numbers'] = results
            #     json_file_name = self.output_dir + "/" + self.target + "_fwingsnumber.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)

            st.write(t)
        else:
            st.write("Sorry! No results found :-(\n"  )

    def get_fwersnumber(self):
        if self.check_private_profile():
            return

        followings = []

        try:

            st.write("Searching for phone numbers of users followers... this can take a few minutes\n")

            rank_token = AppClient.generate_uuid()
            data = self.api.user_following(str(self.target_id), rank_token=rank_token)

            for user in data.get('users', []):
                u = {
                    'id': user['pk'],
                    'username': user['username'],
                    'full_name': user['full_name']
                }
                followings.append(u)

            next_max_id = data.get('next_max_id')

            while next_max_id:
                results = self.api.user_following(str(self.target_id), rank_token=rank_token, max_id=next_max_id)

                for user in results.get('users', []):
                    u = {
                        'id': user['pk'],
                        'username': user['username'],
                        'full_name': user['full_name']
                    }
                    followings.append(u)

                next_max_id = results.get('next_max_id')

            results = []

            print("Do you want to get all phone numbers? y/n: " )
            value = len(followings)


            for follow in followings:
                sys.stdout.write("\rCatched %i followers phone numbers" % len(results))
                sys.stdout.flush()
                user = self.api.user_info(str(follow['id']))
                if 'contact_phone_number' in user['user'] and user['user']['contact_phone_number']:
                    follow['contact_phone_number'] = user['user']['contact_phone_number']
                    if len(results) > value:
                        break
                    results.append(follow)
        except ClientThrottledError as e:
            print("\nError: Instagram blocked the requests. Please wait a few minutes before you try again.")
            print("\n")

        print("\n")

        if len(results) > 0:
            t = PrettyTable(['ID', 'Username', 'Full Name', 'Phone'])
            t.align["ID"] = "l"
            t.align["Username"] = "l"
            t.align["Full Name"] = "l"
            t.align["Phone number"] = "l"

            json_data = {}

            for node in results:
                t.add_row([str(node['id']), node['username'], node['full_name'], node['contact_phone_number']])
            #
            # if self.writeFile:
            #     file_name = self.output_dir + "/" + self.target + "_fwersnumber.txt"
            #     file = open(file_name, "w")
            #     file.write(str(t))
            #     file.close()
            #
            # if self.jsonDump:
            #     json_data['followings_phone_numbers'] = results
            #     json_file_name = self.output_dir + "/" + self.target + "_fwerssnumber.json"
            #     with open(json_file_name, 'w') as f:
            #         json.dump(json_data, f)

            st.write(t)
        else:
            st.write("Sorry! No results found :-(\n"  )


    def get_comments(self):
        if self.check_private_profile():
            return

        st.write("Searching for users who commented...\n")

        data = self.__get_feed__()
        users = []

        for post in data:
            comments = self.__get_comments__(post['id'])
            for comment in comments:
                # Check if the user is already in the list
                if not any(u['id'] == comment['user']['pk'] for u in users):
                    user = {
                        'id': comment['user']['pk'],
                        'username': comment['user']['username'],
                        'full_name': comment['user']['full_name'],
                        'counter': 1
                    }
                    users.append(user)
                else:
                    for user in users:
                        if user['id'] == comment['user']['pk']:
                            user['counter'] += 1
                            break

        if len(users) > 0:
            # Sort users based on the number of comments
            ssort = sorted(users, key=lambda value: value['counter'], reverse=True)

            # Create a DataFrame to hold the user data
            data_dict = {
                'Comments': [str(u['counter']) for u in ssort],
                'ID': [u['id'] for u in ssort],
                'Username': [u['username'] for u in ssort],
                'Full Name': [u['full_name'] for u in ssort]
            }
            df = pd.DataFrame(data_dict)

            # Display the DataFrame as a table in Streamlit without the index
            st.dataframe(df, use_container_width=True,hide_index=True)  # Use st.dataframe for an interactive table

        else:
            st.write("Sorry! No results found :-(\n")

    def clear_cache(self):
        try:
            f = open("settings.json", 'w')
            f.write("{}")
            print("Cache Cleared.\n" )
        except FileNotFoundError:
            print("Settings.json don't exist.\n"  )
        finally:
            f.close()



