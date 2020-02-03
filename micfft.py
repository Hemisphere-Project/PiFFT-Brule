import pyaudio

import numpy as np
from scipy import signal

# import matplotlib.pyplot as plt

from collections import OrderedDict 
from threading import Thread, Lock, Event
import copy
import time
import cherrypy
import socket

mutex = Lock()

RATE = 44100
CHUNK = 1024*4   # Buffer size

BANDS = 20
FREQSTEP = 100

NUM_STREAM = 1  # NUMBER OF DISTINCT SOUND CARDS
NUM_CHANNEL = 2 # NUMBER OF CHANNELS ON SOUND CARDS

# List Devices
p = pyaudio.PyAudio()
info = p.get_host_api_info_by_index(0)
numdevices = info.get('deviceCount')
for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            print ("Input Device id ", i, " - ", p.get_device_info_by_host_api_device_index(0, i).get('name'))



# Open audio input
audio = pyaudio.PyAudio()

# start Recording
streams = [None]*NUM_STREAM
for i in range(NUM_STREAM):
    streams[i] = audio.open(format=pyaudio.paInt16,
                    channels=NUM_CHANNEL,
                    rate=RATE,
                    input_device_index = (2+i),
                    input=True,
                    frames_per_buffer=CHUNK)



# Define FREQ bands
global FREQ_bands
FREQ_bands = OrderedDict()
for f in range(0,BANDS):
    FREQ_bands[ str( (f+1)*FREQSTEP ) ] = ((f+1)*FREQSTEP-FREQSTEP/2, (f+2)*FREQSTEP-FREQSTEP/2)

# Stores
global FREQ_band_fft
FREQ_band_fft = [OrderedDict()]*NUM_STREAM*NUM_CHANNEL
for i in range(NUM_STREAM):
    for j in range(NUM_CHANNEL):
        for band in FREQ_bands:  
            FREQ_band_fft[i*NUM_CHANNEL+j][band] = 0 

global audio_data
audio_data = [None]*NUM_STREAM*NUM_CHANNEL

global fft_dbs 
fft_dbs = [None]*NUM_STREAM*NUM_CHANNEL

global ready
ready = False



#
# GRAPH
#

# f,ax = plt.subplots(3)
# f.set_size_inches(15,8)

# # Prepare the Plotting Environment with random starting values
# x = np.arange(10000)
# y = np.random.randn(10000)

# # Plot 0 is for raw audio data
# li, = ax[0].plot(x, y)
# ax[0].set_xlim(0,CHUNK)
# ax[0].set_ylim(-5000,5000)
# ax[0].set_title("Raw Audio Signal")

# # Plot 1 is for the FFT of the audio
# li2, = ax[1].plot(x, y)
# ax[1].set_xlim(0,(BANDS)*FREQSTEP)
# ax[1].set_ylim(50,100)
# ax[1].set_title("FFT spectrum (dB / Hz)")

# # Plot 2 is for the FFT of the audio
# li3 = ax[2].bar( FREQ_bands.keys(), [FREQ_band_fft[band] for band in FREQ_bands])
# ax[2].set_ylim(50,100)
# ax[2].set_title("FFT average bands (dB / Hz)")


# # Show the plot, but without blocking updates
# plt.pause(0.01)
# plt.tight_layout()


def compute():

    for i in range(NUM_STREAM):

        # try:
            in_data = streams[i].read(CHUNK, exception_on_overflow = False)

            # get and convert the data to float, split per channels
            data = np.frombuffer(in_data, np.int16)
            data = np.reshape(data, (CHUNK, NUM_CHANNEL))

            # Lock
            mutex.acquire()
            global audio_data

            for j in range(NUM_CHANNEL):

                # remove DC offset
                audio_data[i*NUM_CHANNEL+j] = signal.detrend(data[:, j])

                # Get real amplitudes of FFT (only in postive frequencies)
                fft_vals = np.absolute(np.fft.rfft(audio_data[i*NUM_CHANNEL+j]))

                # Get frequencies for amplitudes in Hz
                fft_freq = np.fft.rfftfreq(len(audio_data[i*NUM_CHANNEL+j]), 1.0/RATE)

                # Fast Fourier Transform, 10*log10(abs) is to scale it to dB
                global fft_dbs 
                fft_dbs[i*NUM_CHANNEL+j] = 10.*np.log10(fft_vals)

                # Take the mean of the fft amplitude for each FREQ band
                global FREQ_band_fft 
                FREQ_band_fft[i*NUM_CHANNEL+j] = dict()
                for band in FREQ_bands:  
                    freq_ix = np.where((fft_freq >= FREQ_bands[band][0]) & 
                                    (fft_freq <= FREQ_bands[band][1]))[0]
                    FREQ_band_fft[i*NUM_CHANNEL+j][band] = np.max(fft_dbs[i*NUM_CHANNEL+j][freq_ix])    
                    # if FREQ_band_fft[i*NUM_CHANNEL+j][band] > 65:
                    #     print(str(FREQ_band_fft[i*NUM_CHANNEL+j][band])+"db") 

                # New data available
                global ready
                ready = True

            # Unlock
            mutex.release()

        # except Exception as e: 
        #     print('flux', i, e)



# def plot():

#     # Lock
#     mutex.acquire()

#     # Copy data to work on
#     ad = copy.copy(audio_data)
#     fd = copy.copy(fft_dbs)
#     Fb = copy.copy(FREQ_band_fft)

#     # Unlock
#     mutex.release()

#     global ready
#     if ready:
#         # Force the new data into the plot, but without redrawing axes.
#         # If uses plt.draw(), axes are re-drawn every time
#         li.set_xdata(np.arange(len(ad)))
#         li.set_ydata(ad)
#         li2.set_xdata(np.arange(len(fd)) * RATE/CHUNK)
#         li2.set_ydata(fd)
        
#         ax[2].clear()
#         ax[2].bar( FREQ_bands.keys(), [Fb[band] for band in FREQ_bands])
#         ax[2].set_ylim(50,100)
#         ax[2].set_title("Frequency bands (dB / Hz)")

#         ready = False

#     # Show the updated plot, but without blocking
#     plt.pause(0.01)


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

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
        # print(s.getsockname())
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

cherrypy.tree.mount(HelloWorld())
cherrypy.config.update({
                        'server.socket_host': '0.0.0.0',
                        'server.port': 8080,
                        'log.screen': False,
                        'log.access_file': '',
                        'log.error_file': ''})
cherrypy.engine.start()


# Open the connection and start streaming the data
for s in streams:
    s.start_stream()
print ("\n+---------------------------------+")
print ("| Press Ctrl+C to Break Recording |")
print ("+---------------------------------+\n")
print ("JSON API: http://"+get_ip()+":8080\n")

# Loop so program doesn't end while the stream callback's
# itself for new data
while True:
    try:
        # plot()
        time.sleep(0.1)
    except:
        break

print("stop")
cherrypy.engine.stop()
computer.stop()
for s in streams:
    s.stop_stream()
    s.close()
audio.terminate()
