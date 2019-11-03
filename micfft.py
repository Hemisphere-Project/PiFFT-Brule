import pyaudio

import numpy as np
from scipy import signal

import matplotlib.pyplot as plt

from collections import OrderedDict 
from threading import Thread, Lock, Event
import copy

import cherrypy

mutex = Lock()

i=0
f,ax = plt.subplots(3)
f.set_size_inches(15,8)

RATE = 44100
CHUNK = 2048   # Buffer size

BANDS = 20
FREQSTEP = 100

# Open audio input
audio = pyaudio.PyAudio()

# start Recording
stream = audio.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    input=True)#,
                    #frames_per_buffer=CHUNK)

# Define FREQ bands
global FREQ_bands
FREQ_bands = OrderedDict()
for i in range(0,BANDS):
    FREQ_bands[ str( (i+1)*FREQSTEP ) ] = (i*FREQSTEP, (i+1)*FREQSTEP)

global FREQ_band_fft
FREQ_band_fft = OrderedDict()
for band in FREQ_bands:  
    FREQ_band_fft[band] = 0 

global audio_data
audio_data = stream.read(CHUNK)

global fft_vals
fft_vals = None

global fft_dbs 
fft_dbs = None

global ready
ready = False


#
# GRAPH
#

# Prepare the Plotting Environment with random starting values
x = np.arange(10000)
y = np.random.randn(10000)

# Plot 0 is for raw audio data
li, = ax[0].plot(x, y)
ax[0].set_xlim(0,CHUNK)
ax[0].set_ylim(-5000,5000)
ax[0].set_title("Raw Audio Signal")

# Plot 1 is for the FFT of the audio
li2, = ax[1].plot(x, y)
ax[1].set_xlim(0,(BANDS)*FREQSTEP)
ax[1].set_ylim(50,100)
ax[1].set_title("Fast Fourier Transform")

# Plot 2 is for the FFT of the audio
li3 = ax[2].bar( FREQ_bands.keys(), [FREQ_band_fft[band] for band in FREQ_bands])
ax[2].set_ylim(50,100)
ax[2].set_title("FFT average bands")


# Show the plot, but without blocking updates
plt.pause(0.01)
plt.tight_layout()


def compute():

    in_data = stream.read(CHUNK)

    # Lock
    mutex.acquire()

    # get and convert the data to float
    global audio_data
    audio_data = np.fromstring(in_data, np.int16)

    # remove DC offset
    audio_data = signal.detrend(audio_data)

    # Get real amplitudes of FFT (only in postive frequencies)
    global fft_vals
    fft_vals = np.absolute(np.fft.rfft(audio_data))

    # Fast Fourier Transform, 10*log10(abs) is to scale it to dB
    global fft_dbs 
    fft_dbs = 10.*np.log10(fft_vals)

    # Get frequencies for amplitudes in Hz
    fft_freq = np.fft.rfftfreq(len(audio_data), 1.0/RATE)

    # Take the mean of the fft amplitude for each FREQ band
    global FREQ_band_fft 
    FREQ_band_fft = dict()
    for band in FREQ_bands:  
        freq_ix = np.where((fft_freq >= FREQ_bands[band][0]) & 
                        (fft_freq <= FREQ_bands[band][1]))[0]
        FREQ_band_fft[band] = np.max(fft_dbs[freq_ix])    
        # if FREQ_band_fft[band] > 65:
        #     print(str(FREQ_band_fft[band])+"db") 

    # New data available
    global ready
    ready = True

    # Unlock
    mutex.release()      


def plot():

    # Lock
    mutex.acquire()

    # Copy data to work on
    ad = copy.copy(audio_data)
    fd = copy.copy(fft_dbs)
    Fb = copy.copy(FREQ_band_fft)

    # Unlock
    mutex.release()

    global ready
    if ready:
        # Force the new data into the plot, but without redrawing axes.
        # If uses plt.draw(), axes are re-drawn every time
        li.set_xdata(np.arange(len(ad)))
        li.set_ydata(ad)
        li2.set_xdata(np.arange(len(fd))*10.)
        li2.set_ydata(fd)
        
        ax[2].clear()
        ax[2].bar( FREQ_bands.keys(), [Fb[band] for band in FREQ_bands])
        ax[2].set_ylim(50,100)

        ready = False

    

    # Show the updated plot, but without blocking
    plt.pause(0.01)


class ComputeThread(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.stopped = Event()
        self.stopped.clear()

    def stop(self):
        self.stopped.set()
        self.join()

    def run(self):
        print("start")
        while not self.stopped.is_set():
            compute()
        print("exit")

computer = ComputeThread()
computer.start()


class HelloWorld(object):
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def index(self):
        mutex.acquire()
        Fb = copy.copy(FREQ_band_fft)
        mutex.release()
        return Fb

cherrypy.tree.mount(HelloWorld())
cherrypy.config.update({'log.screen': False,
                        'log.access_file': '',
                        'log.error_file': ''})
cherrypy.engine.start()


# Open the connection and start streaming the data
stream.start_stream()
print ("\n+---------------------------------+")
print ("| Press Ctrl+C to Break Recording |")
print ("+---------------------------------+\n")
print ("JSON API: 0.0.0.0:8080\n")

# Loop so program doesn't end while the stream callback's
# itself for new data
while True:
    try:
        plot()
    except:
        break

print("stop")
cherrypy.engine.stop()
computer.stop()
stream.stop_stream()
stream.close()

audio.terminate()