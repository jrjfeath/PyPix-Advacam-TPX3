import os
import sys
import matplotlib.pyplot as plt
import numpy as np
import h5py
import time
from PyQt6 import uic, QtWidgets, QtCore, QtGui

save_directory = r'C:\Users\mb\Documents\timepix\Dongus'
save_file = '23-8-24.h5'
config_file = 'Q:/Cameras/TimePix/FITPix-H08-W0028.xml'
bias = 50
runtime = 120.0
threshold = 0 # Value between 1-1000

# Program MUST be run out of the PIXET Pro installation directory
os.chdir('C:/Program Files/PIXet Pro')
sys.path.append('C:/Program Files/PIXet Pro')
# Import the camera and UI libraries
import pypixet

# Initialise the pypixet class
if pypixet.start() != 0:
    print('Cannot start pypixet, are you running from the correct directory?')
    exit()
pixet = pypixet.pixet

def create_savefile():
    hf = h5py.File(f'{save_directory}/{save_file}', 'w')
    hf.create_group('Index')
    hf.create_group('ToT')
    hf.create_group('CToA')
    hf.create_group('FToA')
    hf.create_group('ToA')
    hf.close()

def simple_acquisition(dev, count = 1, time = 1.0):
    '''Acquire x frames for x duration'''
    print("dev.doSimpleAcquisition (3 frames @ 1 sec) - start")
    rc = dev.doSimpleAcquisition(count, time, pixet.PX_FTYPE_AUTODETECT, "")
    print("dev.doSimpleAcquisition - end:", rc, "(0 is OK)")
    # Page 27
    frame = dev.lastAcqFrameRefInc() 
    if frame.subFrameCount()>0: 
        for sfr in frame.subFrames(): 
            print(" Subframe:", sfr.frameName())
            data = sfr.data()
            plt.imshow(data)
            sfr.destroy()
    frame.destroy()

start = 0
def new_data(unused):
    '''Function is called each time datadriven mode dumps to memory.'''
    current_time = round(time.time()-start,2)
    print(f'Runtime: {current_time}')
    pixels = dev.lastAcqPixelsRefInc() 
    # [0] Pixel Index [1] ToA (ns) [2] ToT (0-1022) pg 12
    pixelsData = np.array(pixels.pixels())
    pixelsRaw = np.array(pixels.rawPixels())
    pixels.destroy()
    # Convert arrays into smaller data formats
    CToA = np.array(pixelsRaw[1], dtype=np.int32)
    FToA = np.array(pixelsRaw[3], dtype=np.int8)
    ToT = np.array(pixelsRaw[4], dtype=np.uint16)
    Idx = np.array(pixelsRaw[0], dtype=np.uint16)
    ToA = np.array(pixelsData[1], dtype=float)
    # # Remove indices below threshold
    # indices = np.argwhere(ToT > threshold)
    # Idx = Idx[indices]
    # ToT = ToT[indices]
    # ToA = ToA[indices]
    # Save data
    hf = h5py.File(f'{save_directory}/{save_file}', 'a')
    hf['Index'].create_dataset(f'{current_time}', data=Idx, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
    hf['ToT'].create_dataset(f'{current_time}', data=ToT, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
    hf['CToA'].create_dataset(f'{current_time}', data=CToA, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
    hf['FToA'].create_dataset(f'{current_time}', data=FToA, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
    hf['ToA'].create_dataset(f'{current_time}', data=ToA, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
    hf.close()

def advanced_acquisition(dev, count = 1, time = 5.0, acqtype = pixet.PX_ACQTYPE_DATADRIVEN):
    # Page 52 API Manual
    dev.registerEvent(pixet.PX_EVENT_ACQ_NEW_DATA, 0, new_data)
    rc = dev.doAdvancedAcquisition(count, time, acqtype, pixet.PX_ACQMODE_NORMAL, pixet.PX_FTYPE_AUTODETECT, 0, "")
    dev.unregisterEvent(pixet.PX_EVENT_ACQ_NEW_DATA, 0, new_data)

devices = pixet.devicesByType(pixet.PX_DEVTYPE_TPX3)
if len(devices) == 0:
    print('Cannot find timepix, is it open in another program?')
    exit()

dev = devices[0]
print(f'Connected to {dev.fullName()}!')
dev.loadConfigFromFile(config_file)
dev.setBias(bias)
print(f'Loaded config and set bias to {bias}')
create_savefile()
dev.setOperationMode(pixet.PX_TPX3_OPM_TOATOT)
print('Setting mode to ToA/ToT')
dev.doSensorRefresh()
start = time.time()
advanced_acquisition(dev, time=runtime)
pixet.exitPixet()