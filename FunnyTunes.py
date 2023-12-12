# For reading and writing database files
import json
import os
import time
import re as regex
from shutil import rmtree
from zipfile import ZipFile

# Interacting with LastFM's API
import requests
import webbrowser
import threading
from bs4 import BeautifulSoup

# Encryption
from backports.pbkdf2 import pbkdf2_hmac
from base64 import urlsafe_b64encode
from cryptography.fernet import Fernet, InvalidToken

# GUI and image rendering
from PIL import ImageTk, UnidentifiedImageError
from PIL import Image as PILImage
from tkinter import *
from tkinter.filedialog import askopenfilename

# LastFM API Key
API_KEY = ''

# Declaring global variables
listeningData = {}
downloadQueue = []
topArtists = []
topSongs = []
dbKey = ''


# Returns an artist's "tags" and similar artists
def getArtistData(artistName):
    global listeningData

    # https://www.last.fm/api/show/artist.getInfo
    params = {
        'method': 'artist.getinfo',
        'artist': artistName,
        'api_key': API_KEY,
        'autocorrect': '1',
        'format': 'json'
    }

    # Make GET request to API
    response = requests.get('http://ws.audioscrobbler.com/2.0/', params=params)

    # If a response was returned (existence validation)
    if response:
        responseData = response.json()
        artistTags = [tag['name'] for tag in responseData['artist']['tags']['tag'] if tag]

        # The API doesn't always have data for related artists
        if responseData['artist']['similar']['artist']:
            similarArtists = [Artist['name'] for Artist in responseData['artist']['similar']['artist']]
            listeningData[artistName]['similar'] = similarArtists[:3]

        # Update existing database
        listeningData[artistName]['tags'] = artistTags


# Retrieves an artist's profile image as a URL and passes it to the imageDL to be downloaded.
# Because of copyright, LastFM's API does not provide images so they need to be manually scraped from the website.
# If an image is unavaliable either because of copyright or because the artist doesn't have an image,
# A star will be displayed instead.
def getArtistImage(artistName):
    # Download the website's html
    response = requests.get(f'https://www.last.fm/music/{artistName}')

    # Parse html
    html = BeautifulSoup(response.text, 'html.parser')

    # Find the artist's image URL in the page
    imageURL = html.find('meta', {'property': 'og:image'})['content']

    # Download the image
    imageDL(imageURL, artistName, artistName)


# Downloads an image from a URL
def imageDL(imageURL, artistName, fileName):
    # The image's file type (.png, .jpg, .webp, etc...)
    fileType = imageURL.rsplit('.', 1)[1]

    # Replace forbidden file characters with an underscore
    safeArtistName = regex.sub(r'[\\/*?:"<>|.]', '_', artistName)
    safeFileName = regex.sub(r'[\\/*?:"<>|.]', '_', fileName)

    # If the folder where the image will be stored does not yet exist, create it
    if not os.path.isdir(f'Images/Artists/{safeArtistName}'):
        os.mkdir(f'Images/Artists/{safeArtistName}')

    # Open file as bytes and write data
    with open(f'Images/Artists/{safeArtistName}/{safeFileName}.{fileType}', 'wb') as image:
        data = requests.get(imageURL).content
        image.write(data)


# Retrieves a song's cover art and the album it's from if it is not a single
def getSongImage(songInfo):
    global listeningData
    song, artist = songInfo

    # https://www.last.fm/api/show/track.getInfo
    params = {
        'method': 'track.getInfo',
        'track': song,
        'artist': artist,
        'api_key': API_KEY,
        'autocorrect': '1',
        'format': 'json'
    }

    # Make request and retrieve track data
    response = requests.get('http://ws.audioscrobbler.com/2.0/', params=params)
    responseData = response.json()['track']

    # If the song is in an album and was not released as a single
    if 'album' in responseData:
        responseData = responseData['album']
        albumTitle = responseData['title']
        imageURL = responseData['image'][2]['#text']

        # Replace forbidden file characters with an underscore
        safeAlbum = regex.sub(r'[\\/*?:"<>.|]', '_', albumTitle)

        # The image's file type (.png, .jpg, .webp, etc...)
        imageType = '.' + imageURL.rsplit('.', 1)[1]

        # Update listening database with the image's file name and the album the song is from
        listeningData[artist]['tracks'][song]['file'] = safeAlbum + imageType
        listeningData[artist]['tracks'][song]['album'] = albumTitle

        # Download the image
        imageDL(imageURL, artist, albumTitle)
    else:
        # Replace forbidden file characters with an underscore
        safeArtist = regex.sub(r'[\\/*?:"<>.|]', '_', artist)

        # Update listening database with the image's file name and use the song's title as the "album"
        listeningData[artist]['tracks'][song]['file'] = safeArtist + '.jpg'
        listeningData[artist]['tracks'][song]['album'] = song

        # If the artist's profile picture is yet to be downloaded, queue it for download
        if not os.path.isdir(f'Images/Artists/{artist}'):
            downloadQueue.append((getArtistImage, [artist]))


# Formats the streaming history provided by spotify into one sorted file
def formatDB():
    # Array of all streaming history .json files
    streamLogs = [fileName for fileName in os.listdir('Spotify Data/MyData') if fileName.startswith('StreamingHistory')]
    data = {}

    # Read each listening log file
    for fileName in streamLogs:
        # Use UTF-8 encoding so unique characters can be read
        with open('Spotify Data/Mydata/' + fileName, encoding='utf-8') as txt:
            rawData = json.load(txt)

            # Iterates over every song played individually
            for listen in rawData:
                artist = listen['artistName']
                msPlayed = listen['msPlayed']
                trackName = listen['trackName']

                # Only save if at least 30 seconds of the song have been played
                if int(msPlayed) >= 30000:
                    # If the artist has been saved before
                    if artist in data:
                        # If this song has been saved before
                        if trackName in data[artist]['tracks']:
                            # Increment listens amount
                            data[artist]['tracks'][trackName]['listens'] += 1
                        else:
                            data[artist]['tracks'][trackName] = {'listens': 1}

                        # Increase total listening time for the artist
                        data[artist]['totalListening'] += msPlayed
                    else:
                        # Save artist, track and listening time
                        data[artist] = {'tracks': {trackName: {'listens': 1}}}
                        data[artist]['totalListening'] = msPlayed

    # Sort by total listening data
    sortedData = {}

    # Save the top fifty artists
    for _ in range(50):
        highestValue = 0
        highestArtist = ''

        # Iterate over each artist
        for artist in data.keys():
            # The total amount of time in milliseconds spent listening to this artist
            artistListening = data[artist]['totalListening']

            # (ignores strange pycharm warning)
            # noinspection PyTypeChecker
            if artistListening >= highestValue:
                # This artist has more listening time than the previous, so update variables
                highestValue = artistListening
                highestArtist = artist

        # Spotify uses "Unknown Artist" when it doesn't recognise the artist, we don't need this data
        if highestArtist != 'Unknown Artist':
            # Append the highest current artist to the sorted dict
            sortedData[highestArtist] = data[highestArtist]

        # Remove the artist with the highest amount of listening time from unsorted dict
        del data[highestArtist]

    # Remove extracted folder
    rmtree('Spotify Data')

    # Convert the database from a dictionary to a string, then encode the string to bytes
    stringJson = json.dumps(sortedData)
    bytesJson = stringJson.encode('utf-8')

    return bytesJson


# Thread responsible for starting queued requests, five at a time with a pause in between to avoid rate limits
def downloadData():
    global downloadQueue

    # Runs in the background forever
    while True:
        threads = []

        # Start first five requests
        for _ in range(5):
            # If the queue is not empty
            if downloadQueue:
                # Get the first item from the queue, then remove it
                target, args = downloadQueue[0]
                downloadQueue.pop(0)

                # Start the thread
                downloadThread = threading.Thread(target=target, args=args)
                downloadThread.start()

                threads.append(downloadThread)

        # Wait until the threads have finished
        for thread in threads:
            thread.join()

        # Limit requests to not put strain on the LastFM API
        # Causes slower load times as a result :(
        time.sleep(1)


# Attempts to load an image and returns a placeholder if the image is not yet downloaded
def loadImage(loadedImages, placeHolders, artistImage, artistOrSong, width):
    # If the image has been downloaded but hasn't been displayed yet (existence validation)
    if os.path.isfile(artistImage) and artistOrSong not in loadedImages:
        try:
            # Attempt to load the image and resize it to the correct dimensions
            imageObject = ImageTk.PhotoImage(PILImage.open(artistImage).resize((width, width)))
            loadedImages.append(artistOrSong)
        except UnidentifiedImageError:
            # The file exists but the image is still being downloaded
            return
    # If the image does not exist yet and a placeholder has not yet been displayed
    elif not os.path.isfile(artistImage) and artistOrSong not in placeHolders:
        # Display a placeholder while the image downloads and resize it to the correct dimensions
        imageObject = ImageTk.PhotoImage(PILImage.open('Assets/placeholder.png').resize((width, width)))
        placeHolders.append(artistOrSong)
    else:
        return
    return imageObject


def loadArtist(loadedImages, placeHolders, artist, width):
    # Replace forbidden file characters with an underscore
    safeArtistName = regex.sub(r'[\\/*?:"<>.|]', '_', artist)
    safeFileName = regex.sub(r'[\\/*?:"<>.|]', '_', artist) + '.jpg'

    # File path to the artist's image
    artistImage = f'Images/Artists/{safeArtistName}/{safeFileName}'

    # If the image has not been loaded yet
    if artistImage not in loadedImages:
        return loadImage(loadedImages, placeHolders, artistImage, artist, width)


# Main GUI Class
class GUI(Tk):
    def __init__(self):
        Tk.__init__(self)

        # Window config
        self.resizable(False, False)
        self.title('FunnyTunes')
        self.geometry('800x600')

        # Create window to store frames in
        self.window = Frame(self)
        self.window.pack(side="top", fill="both", expand=True)
        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        # If a listening database already exists
        if os.path.isfile('ListeningDB.json'):
            self.showFrame(PasswordScreen(self.window, True, self))
        else:
            # Display the start window
            start = StartScreen(self.window, self)
            start.grid(row=0, column=0, sticky="nsew")

    @staticmethod
    def showFrame(frame):
        # Grid the frame and then raise it to be visible
        frame.grid(row=0, column=0, sticky="nsew")
        frame.tkraise()


# Screen displayed upon launching the program
class StartScreen(Frame):
    def __init__(self, window, main):
        Frame.__init__(self, window)

        # Window config
        self.window = window
        self.main = main
        self['bg'] = 'black'

        # Logo text
        self.logoText = PhotoImage(file="Assets/logoWhite.png")
        Label(self, image=self.logoText, bg='black').place(x=0, y=0)

        # Button images
        self.zipImage = PhotoImage(file="Assets/zipImage.png")
        self.spotifyImage = PhotoImage(file="Assets/spotifyImage.png")

        Button(self, image=self.zipImage, borderwidth=0, padx=0, pady=0,
               highlightthickness=0, command=self.selectZip).place(x=28, y=478)
        Button(self, image=self.spotifyImage, borderwidth=0, padx=0, pady=0,
               highlightthickness=0, command=self.spotifyWeb).place(x=420, y=478)

        # Instructions to download spotify data
        guideText = """
    How to download your Spotify data:
    Step 1: Click "Spotify Website"
    Step 2: Request to download your data
    Step 3: Wait a day or two for an email
    Step 4: Download the zip file from the email and select it
        """
        Label(self, text=guideText, bg='black', fg='white', font=('', 25), justify=LEFT).place(x=0, y=180)

        # Cat :D
        self.logoCat = PhotoImage(file="Assets/logo.png")
        Label(self, image=self.logoCat, bg='black').place(x=480, y=0)

    @staticmethod
    def spotifyWeb():
        # Opens the user's browser to the spotify page so they can download their data
        webbrowser.open('https://www.spotify.com/us/account/privacy/')

    # Launches a finder window to select a zip file to be extracted and processed
    def selectZip(self):
        spotifyZip = askopenfilename(title="Select Spotify Zip File",
                                     filetypes=(("zip", "*.zip"), ("All Files", "*,*")))

        # If the user has selected a file
        if spotifyZip:
            # Open zip file and extract all items within it
            with ZipFile(spotifyZip, 'r') as file:
                file.extractall('Spotify Data')

            # Display the password prompt screen
            self.main.showFrame(PasswordScreen(self.window, False, self.main))


# Screen where user is asked for a password to either encrypt or decrypt their database
class PasswordScreen(Frame):
    def __init__(self, window, encrypted, main):
        Frame.__init__(self, window)

        # Window config
        self.window = window
        self.encrypted = encrypted
        self.main = main
        self['bg'] = 'black'

        # Logo Images
        self.logoText = PhotoImage(file="Assets/logoWhite.png")
        Label(self, image=self.logoText, bg='black').place(x=0, y=0)

        self.logoCat = PhotoImage(file="Assets/logo.png")
        Label(self, image=self.logoCat, bg='black').place(x=480, y=0)

        if encrypted:
            # The database has already been encrypted
            dbText = 'A listening database already exists, please enter your password: '
        else:
            # The database is not encrypted
            dbText = 'Please enter a password to encrypt the database: '

        # Password elements
        Label(self, text=dbText, bg='black', fg='white', font=('', 23), justify=LEFT).place(x=95, y=280)
        Button(self, text='Continue', font=('', 15), command=self.openDB, width=9, height=2).place(x=600, y=350)

        self.passwordBox = Entry(self, bg='grey20', show='*', font=('', 22), width=34)
        self.passwordBox.place(x=100, y=350)

    # Decrypts the database and formats data
    def openDB(self):
        global dbKey, listeningData, topArtists, topSongs

        # Get the user's password input
        dbPassword = self.passwordBox.get().encode('utf-8')

        # Convert user's password into a private key capable of encryption, then base64 encode the key
        dbKey = urlsafe_b64encode(pbkdf2_hmac('sha256', dbPassword, b'', 1000, 32))
        crypto = Fernet(dbKey)

        # If the data has been encrypted already
        if self.encrypted:
            # Read file as bytes
            with open('ListeningDB.json', 'rb') as file:
                try:
                    # Decrypt the encrypted data
                    plainText = crypto.decrypt(file.read())
                except InvalidToken:
                    Label(self, text='Incorrect Password', bg='black', fg='red', font=('', 25)).place(x=280, y=400)
                    return
        else:
            # Format the extracted database
            plainText = formatDB()
            encryptedData = crypto.encrypt(plainText)

            # Open file as bytes to write encrypted data
            with open('ListeningDB.json', 'wb') as file:
                file.write(encryptedData)

        # Load database as a dictionary
        listeningData = json.loads(plainText)

        # The amount of songs saved
        songAmount = len([listeningData[artist]['tracks'] for artist in listeningData.keys()])

        # Temporarily fill lists with junk data to be replaced
        topArtists = [_ for _ in range(50)]
        topSongs = [(_, _) for _ in range(songAmount)]

        # Top artists
        for index in range(50):
            runningHighest = 0
            for artist in listeningData:
                # The total time spent listening to the artist in milliseconds
                totalListening = listeningData[artist]['totalListening']

                # If this artist is not yet saved, set it to the next top artist
                if totalListening > runningHighest and artist not in topArtists:
                    runningHighest = totalListening

                    # Take the place of the last top artist
                    topArtists[index] = artist

        # Find the top songs
        for index in range(songAmount):
            runningHighest = 0
            for artist in listeningData:
                songs = listeningData[artist]['tracks']
                for song in songs:
                    # The amount of times a song has been listened to
                    songListening = songs[song]['listens']

                    # If this song is not yet saved, set it to the next top song
                    if songListening > runningHighest and (song, artist) not in topSongs:
                        runningHighest = songListening

                        # Take the place of the last top song
                        topSongs[index] = (song, artist)

        # If images have not yet been downloaded (existence validation)
        if not os.path.isdir('Images'):
            # Create the image folders
            os.mkdir('Images')
            os.mkdir('Images/Artists')

            # Download artist profile images and data
            for artist in topArtists[:6]:
                downloadQueue.append((getArtistImage, [artist]))
                downloadQueue.append((getArtistData, [artist]))

            # Download song images
            for song in topSongs[:3]:
                downloadQueue.append((getSongImage, [song]))

        # Start the download thread
        threading.Thread(target=downloadData, daemon=True).start()

        # Display main screen
        self.main.showFrame(MainScreen(self.window, self.main))


class MainScreen(Frame):
    def __init__(self, window, main):
        Frame.__init__(self, window)

        # Declare class variables
        self.window = window
        self.main = main
        self.active = True
        self.topGenres = []
        self.loadedImages = []
        self.placeHolders = []

        # Grey background
        self['bg'] = 'black'
        self.mainBG = PhotoImage(file="Assets/mainBG.png")
        Label(self, image=self.mainBG, bg='black').place(x=0, y=0)

        # Top labels
        Label(self, text="Top Artists:", bg='black', fg='white', font=('', 17)).place(x=19, y=10)
        Label(self, text="Top Songs:", bg='black', fg='white', font=('', 17)).place(x=19, y=255)
        Label(self, text="Top Genres:", bg='black', fg='white', font=('', 17)).place(x=19, y=490)

        # Top song numbers
        for number in range(3):
            Label(self, text=number + 1, bg='grey9', fg='white', font=('', 18)).place(x=32, y=310 + 59 * number)

        # "View All" button
        self.viewAllImg = PhotoImage(file="Assets/viewAll.png")
        Button(self, borderwidth=0, highlightthickness=0, command=lambda: self.viewAll(ArtistScreen),
               image=self.viewAllImg, padx=0, pady=0).place(x=695, y=20)

        # Top genres
        self.genreLabel = Label(self, bg='grey9', fg='white', font=('', 20))
        self.genreLabel.place(x=25, y=545)

        # Begin loading images and genres thread
        threading.Thread(target=self.ImageLoading, daemon=True).start()
        threading.Thread(target=self.loadGenres, daemon=True).start()

    # Display the screen to view all artists
    def viewAll(self, screen):
        self.active = False
        self.main.showFrame(screen(self.window, self.main))

    def ImageLoading(self):
        # Continue until all artists have their image displayed
        while len(self.loadedImages) != 8:
            # For the top five artists
            for index, artist in enumerate(topArtists[:4]):
                imageObject = loadArtist(self.loadedImages, self.placeHolders, artist, 125)
                if imageObject:
                    # Display image
                    artistPic = Label(self, image=imageObject, bg='black')
                    artistPic.image = imageObject
                    artistPic.place(x=(185 * index) + 50, y=70)

                    # Display name
                    nameLabel = Label(self, text=artist, bg='grey9', fg='white', width=16,
                                      font=('', 13), justify=CENTER)
                    nameLabel.place(x=(185 * index) + 40, y=210)

            # For the top four songs
            for index, data in enumerate(topSongs[:3]):
                song, artist = data

                # For each song, the songInfo includes the amount of times listened, the file path and the album name
                songInfo = listeningData[artist]['tracks'][song]
                safeArtistName = regex.sub(r'[\\/*?:"<>.|]', '_', artist)

                # If the song's image has been downloaded
                if 'file' in songInfo:
                    # Replace forbidden file characters with an underscore
                    fileName = songInfo['file']
                    albumTitle = songInfo['album']
                # Use blank strings to load a placeholder instead
                else:
                    fileName = ''
                    albumTitle = ''

                artistImage = f'Images/Artists/{safeArtistName}/{fileName}'

                # If the image is not yet loaded
                if artistImage not in self.loadedImages:
                    imageObject = loadImage(self.loadedImages, self.placeHolders, artistImage, song, 50)
                    if imageObject:
                        # Display image
                        songCover = Label(self, image=imageObject, bg='black')
                        songCover.image = imageObject
                        songCover.place(x=55, y=(59 * index) + 298)

                        # Display song title
                        songTitle = Label(self, text=song, bg='grey9', fg='white', width=16,
                                          font=('', 15), anchor='w')
                        songTitle.place(x=120, y=(59 * index) + 302)

                        # Display artist name
                        artistTitle = Label(self, text=artist, bg='grey9', fg='white', width=16,
                                            font=('', 13), anchor='w')
                        artistTitle.place(x=120, y=(59 * index) + 325)

                        # Display album name
                        albumLabel = Label(self, text=albumTitle, bg='grey9', fg='white', width=55,
                                           font=('', 13), anchor='e')
                        albumLabel.place(x=270, y=(59 * index) + 320)

    # Updates the top genres label as artist's genres are downloaded
    def loadGenres(self):
        while self.active:
            self.topGenres = []

            # Adds all the genres in a list, with duplicates to be sorted
            for artist in listeningData:
                if 'tags' in listeningData[artist]:
                    for genre in listeningData[artist]['tags']:
                        self.topGenres.append(genre)

            # Sort the top genres by most occurences
            sortedTopGenres = sorted(self.topGenres, key=self.topGenres.count, reverse=True)

            # Add the top five genres to a new list
            topTenGenres = []
            for genre in sortedTopGenres:
                # If five genres have already been added, break the loop
                if len(topTenGenres) == 8:
                    break

                # If the genre has not been saved, add it
                if genre not in topTenGenres:
                    topTenGenres.append(genre)

            # Top five genres as a string seperated by a comma
            strTopGenres = ', '.join(topTenGenres)
            self.genreLabel['text'] = strTopGenres


# Tkinter is poorly optomised so this screen lags a bit on macbooks
class ArtistScreen(Frame):
    def __init__(self, window, main):
        Frame.__init__(self, window)

        # Declare class variables
        self.window = window
        self.main = main
        self.pageNum = 0
        self.active = True

        # Grey background
        self['bg'] = 'black'

        # Button images
        self.backImg = PhotoImage(file="Assets/back.png")
        self.previousImg = PhotoImage(file="Assets/previous.png")
        self.nextImg = PhotoImage(file="Assets/next.png")

        # Next and previous buttons
        self.previous = Button(self, image=self.previousImg, bg='black', command=self.previousPage, borderwidth=0,
                               highlightthickness=0, state='disabled', padx=0, pady=0)
        self.previous.place(x=150, y=540)

        self.next = Button(self, image=self.nextImg, bg='black', command=self.nextPage, borderwidth=0, padx=0, pady=0,
                           highlightthickness=0)
        self.next.place(x=460, y=540)

        # Back button
        Button(self, image=self.backImg, bg='black', command=self.back, borderwidth=0, padx=0, pady=0,
               highlightthickness=0).place(x=20, y=10)

        # Artist text
        self.artistNames = []
        self.artistGenres = []
        self.totalListening = []
        self.mostPlayed = []
        self.relatedArtists = []

        # Create labels for each artist
        for index in range(3):
            artistName = Label(self, bg='black', fg='white', font=('', 22))
            artistName.place(x=180, y=(170 * index) + 45)

            artistGenre = Label(self, bg='black', fg='white', font=('', 19))
            artistGenre.place(x=180, y=(170 * index) + 80)

            totalListening = Label(self, bg='black', fg='white', font=('', 19))
            totalListening.place(x=180, y=(170 * index) + 110)

            mostPlayed = Label(self, bg='black', fg='white', font=('', 19))
            mostPlayed.place(x=180, y=(170 * index) + 140)

            relatedArtists = Label(self, bg='black', fg='white', font=('', 19))
            relatedArtists.place(x=180, y=(170 * index) + 170)

            # Add the window elements to a list so they can be updated easily
            self.artistNames.append(artistName)
            self.artistGenres.append(artistGenre)
            self.totalListening.append(totalListening)
            self.mostPlayed.append(mostPlayed)
            self.relatedArtists.append(relatedArtists)

        # Begin loading the images in another thread
        threading.Thread(target=self.ArtistLoading, daemon=True).start()

    def ArtistLoading(self):
        # Declare variables
        loadedImages = []
        placeHolders = []
        toDownload = []
        currentPage = -1

        # Stop once the back button has been clicked
        while self.active:
            if self.pageNum != currentPage or len(loadedImages) != 3:
                # If a new page is being loaded
                if self.pageNum != currentPage:
                    loadedImages = []
                    placeHolders = []

                # Enable/Disable button interaction
                if self.pageNum == 0:
                    self.previous['state'] = 'disabled'
                elif self.pageNum == 15:
                    self.next['state'] = 'disabled'
                else:
                    self.previous['state'] = 'normal'
                    self.next['state'] = 'normal'

                dbIndex = 3 * self.pageNum
                currentPage = self.pageNum

                # Iterates over the three artists to be displayed
                for index, artist in enumerate(topArtists[dbIndex:dbIndex + 3]):
                    if artist not in loadedImages:
                        safeArtistName = regex.sub(r'[\\/*?:"<>.|]', '_', artist)

                        # Download artist's image if it has not been downloaded already (existence validation)
                        if not os.path.isfile(f'Images/Artists/{safeArtistName}/{safeArtistName}.jpg'):
                            if artist not in toDownload:
                                # The the artist's image and data to the download queue
                                downloadQueue.append((getArtistData, [artist]))
                                downloadQueue.append((getArtistImage, [artist]))
                                toDownload.append(artist)

                        imageObject = loadArtist(loadedImages, placeHolders, artist, 140)
                        if imageObject:
                            # Display image
                            artistPic = Label(self, image=imageObject, bg='black')
                            artistPic.image = imageObject
                            artistPic.place(x=30, y=(170 * index) + 50)

                        # Artist text
                        self.artistNames[index]['text'] = artist

                        # Convert ms to hrs
                        listening = int(listeningData[artist]['totalListening'] / 3600000)
                        self.totalListening[index]['text'] = f'Total Listening: {listening}hrs'

                        # Artist genres
                        characterTotal = 0
                        if 'tags' in listeningData[artist]:
                            # A list of the artists genres
                            tags = listeningData[artist]['tags']

                            # Avoid text being longer than the window
                            for tag in tags:
                                characterTotal += len(tag)

                                # Text can't exceed 39 characters (range validation)
                                if characterTotal > 39:
                                    tags.remove(tag)

                            # Update GUI text
                            self.artistGenres[index]['text'] = f'Genres: {", ".join(tags)}'
                        else:
                            self.artistGenres[index]['text'] = ''

                        # Garbage data
                        artistTracks = ['' for _ in range(3)]

                        # The artist's top three most played songs
                        for songIndex in range(3):
                            runningHighest = 0
                            for track in listeningData[artist]['tracks']:
                                # The amount of times a song has been played
                                listens = listeningData[artist]['tracks'][track]['listens']

                                # If this artist is not yet saved, set it to the next top artist
                                if listens > runningHighest and track not in artistTracks:
                                    runningHighest = listens

                                    # Take the place of the last top artist
                                    artistTracks[songIndex] = track

                        # Avoid text being longer than the window
                        characterTotal = 0
                        for track in artistTracks:
                            characterTotal += len(track)

                            # Text can't exceed 39 characters (range validation)
                            if characterTotal > 39:
                                artistTracks.remove(track)

                        # Update GUI text
                        self.mostPlayed[index]['text'] = f'Most played songs: {", ".join(artistTracks)}'

                        # If related artists have been saved (existence validation)
                        characterTotal = 0
                        if 'similar' in listeningData[artist]:
                            relatedArtists = listeningData[artist]['similar']

                            # Avoid text being longer than the window
                            for relatedArtist in relatedArtists:
                                characterTotal += len(relatedArtist)

                                # Text can't exceed 39 characters (range validation)
                                if characterTotal > 39:
                                    relatedArtists.remove(relatedArtist)

                            # Update GUI text
                            self.relatedArtists[index]['text'] = f'Related artists: {", ".join(relatedArtists)}'
                        else:
                            self.relatedArtists[index]['text'] = ''

    def nextPage(self):
        self.pageNum += 1

    def previousPage(self):
        self.pageNum -= 1

    # Returns GUI to the main page
    def back(self):
        self.active = False
        self.main.showFrame(MainScreen(self.window, self.main))


# Launch the GUI
GUI().mainloop()

# Create cryptography object
encryptor = Fernet(dbKey)

# Save updated database
# If the program is forcefully closed, the data may not save properly and can be corrupted
with open('ListeningDB.json', 'wb') as database:
    # Convert database from a dictionary to a json object, then encode to bytes
    jsonData = json.dumps(listeningData, indent=4, ensure_ascii=False)
    bytesData = jsonData.encode('utf-8')

    # Encrypt database and write data to file
    newData = encryptor.encrypt(bytesData)
    database.write(newData)