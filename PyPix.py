import os
import sys
import matplotlib.pyplot as plt
import numpy as np
import scipy.stats as stats
from scipy.ndimage import label, center_of_mass
import h5py
import time
from PyQt6 import uic, QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from pyqtgraph.widgets.RawImageWidget import RawImageWidget
from sklearn.cluster import DBSCAN #scikit-learn

save_directory = r'C:\Users\mb\Documents\timepix\Dongus'
save_file = '23-8-24.h5'
config_file = 'Q:/Cameras/TimePix/FITPix-H08-W0028.xml'
bias = 50

# Program MUST be run out of the PIXET Pro installation directory
os.chdir('C:/Program Files/PIXet Pro')
scriptPath = os.path.dirname(__file__)
sys.path.append(f'{scriptPath}/Pixet_API')
# Import the camera and UI libraries
import pypixet
# Initialise the pypixet class
if pypixet.start() != 0:
    print('Cannot start pypixet, are you running from the correct directory?')
    exit()
pixet = pypixet.pixet

class ImageAcquisitionThread(QtCore.QThread):
    '''
    Thread for getting images from Timepix.
    '''

    finished = QtCore.pyqtSignal()                     
    '''Emit signal when end of acquisition reached'''
    progress = QtCore.pyqtSignal(list)               
    '''Emit current progress on delay stage position'''
    tot_signal = QtCore.pyqtSignal(list)
    '''Emit tot image and LED location'''
    toa_spectrum_signal = QtCore.pyqtSignal(np.ndarray)
    '''Emit toa times and intensities'''

    def __init__(self, parent=None) -> None:
        QtCore.QThread.__init__(self, parent)
        self.saving     : bool = parent._save_box.isChecked()
        self.run_time   : float = parent._runtime.value()
        self.start_time : float = 1.00
        self.iter       : int = parent._iterations.value()
        self.device = parent.device

        #Create a filename for saving data
        filename = os.path.join(parent._dir_name.text(),parent._file_name.text())
        filename += '_0000.hdf5'
        #Check if file already exists so you dont overwrite data
        fid = 1
        while os.path.exists(filename):
            filename = f'{filename[:-10]}_{fid:04d}.hdf5'
            fid+=1
        self.filename = filename

    def create_savefile(self):
        hf = h5py.File(self.filename, 'w')
        hf.create_group('Index')
        hf.create_group('ToT')
        hf.create_group('ToA')
        hf.close()

    def new_data(self, unused):
        '''Function is called each time datadriven mode dumps to memory.'''
        current_time = round(time.time()-self.start_time,2)
        if current_time > self.run_time: current_time = self.run_time
        remaining_percent = 100 - int(((self.run_time - current_time) / self.run_time) * 100)
        self.progress.emit([remaining_percent,f'{current_time} / {self.run_time}, {remaining_percent}%'])
        pixels = self.device.lastAcqPixelsRefInc()
        # [0] Pixel Index [1] ToA (ns) [2] ToT (0-1022) pg 12
        pixelsData = np.array(pixels.pixels())
        pixelsRaw = np.array(pixels.rawPixels())
        pixels.destroy()
        # Convert arrays into smaller data formats
        ToT = np.array(pixelsRaw[4], dtype=np.uint16)
        Idx = np.array(pixelsRaw[0], dtype=np.uint16)
        ToA = np.array(pixelsData[1], dtype=float)
        if ToA.shape[0] == 0:
            return
        # Save data
        if self.saving:
            hf = h5py.File(self.filename, 'a')
            hf['Index'].create_dataset(f'{current_time}', data=Idx, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
            hf['ToT'].create_dataset(f'{current_time}', data=ToT, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
            hf['ToA'].create_dataset(f'{current_time}', data=ToA, compression="gzip", compression_opts=4, shuffle=True, fletcher32=True)
            hf.close()

        # Get image data, find coordinate data and adjust ToA values if required
        x = np.array(Idx %  256, dtype=np.uint8)           # Calculate x positions
        y = np.array(Idx // 256, dtype=np.uint8)           # Calculate y positions
        time_factor = ((2147483647 * 25) / 2)              # ToA overflows at this value (53.68s)
        maxToA = np.max(ToA)                               # What is the max value?
        minToA = np.min(ToA)                               # What is the min value?
        adjust = np.where((ToA) < 10e9)[0]                 # Find where ToA less than 10s
        if (maxToA > 20e9) and (minToA < 10e9):            # Check to see if toa overflows
            ToA[adjust] = np.add(ToA[adjust], time_factor) # If overflow add time factor to those indices
        minToA = np.min(ToA)                               # What is the min value?
        ToA -= minToA                                      # Subtract the minimum value

        # Now that we have the image data, take a slice and find the LED trigger
        pt = np.argwhere((0.1 * 10 ** 9 < ToA) & (ToA < 1.0 * 10 ** 9))                   # Set a threshold for the image ToA
        xp, yp, zp = x[pt], y[pt], ToT[pt]                                              # Get pixels corresponding to ToA timeframe
        data = np.hstack((xp, yp, zp))                                                  # Create a 3d array of our data
        sorted_indices = np.lexsort((yp.flatten(), xp.flatten()))                       # Sort by y, then x
        sorted_data = data[sorted_indices]                                              # Sort array by sorted indices
        unique_rows, indices = np.unique(sorted_data[:, :2], axis=0, return_index=True) # Find the unique rows and their indices
        summed_third_column = np.add.reduceat(sorted_data[:, 2], indices)               # Add the zd data between each of the indices
        image = np.zeros((256,256))                                                     # Create empty image array
        image[unique_rows[:,0], unique_rows[:,1]] = summed_third_column                 # Fill image with summed intensities
        labels = label(image)                                                           # Finds the unique inputs in the image
        list_of_labels = np.linspace(1, labels[1], labels[1])                           # Make a list of the inputs to iterate through
        for i, l in enumerate(list_of_labels):
            onepix = np.where(labels[0] == l)                                           # Find where labels is equal to x
            if len(onepix[0]) < 50:                                                     # If there are not 50 pixels set it equal to 0
                labels[0][onepix] = 0
                list_of_labels[i] = 0
        list_of_labels = list_of_labels[np.nonzero(list_of_labels)]                     # Get the list of non-zero entries
        coms = (np.round(center_of_mass(image, labels[0], list_of_labels))).astype(int) # Get the center of masses as ints
        if len(coms) == 0: 
            coms = [[False,False]]                                                      # If LED not found pass null value
            self.tot_signal.emit([image, coms[0]])                                      # Emit the ToT image and false LED location
            return
        else:
            self.tot_signal.emit([image, coms[0]])                                      # Emit the ToT image and the LED location

        com = coms[0]
        # Create a list of pixels to check for LED pulses
        led_pixels_x = np.array([p for p in range(com[0]-10,com[0]+10)])
        led_pixels_y = np.array([p for p in range(com[1]-10,com[1]+10)])
        pixel_threshold = 20
        # Get indices of led pixels to get the led time of arrivals, remove any values below the set threshold
        ind = np.where(np.in1d(x,led_pixels_x) & (np.in1d(y,led_pixels_y)) & (ToT >= pixel_threshold))[0]
        pixel_ToA = np.unique(ToA[ind])
        # DBSCAN parameters
        eps = 10000.0  # How many ns do you want to cluster pixels by?
        min_samples = 2  # Minimum number of pixels to form a cluster

        # Apply DBSCAN
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(pixel_ToA.reshape(-1, 1))

        # Get the labels
        labels = clustering.labels_

        # Extract clusters and find the lowest value in each cluster
        clusters = {}
        for index, point in enumerate(pixel_ToA.flatten()):
            cluster_index = labels[index]
            if cluster_index != -1:  # Exclude noise (outliers)
                if cluster_index not in clusters:
                    clusters[cluster_index] = []
                clusters[cluster_index].append(point)

        # Find the lowest value in each cluster
        shot_times = np.array([min(clusters[cluster_index]) for cluster_index in clusters])

        x_data = []
        y_data = []
        ToT_data = []
        ToA_data = {}
        start_idx = 0
        min_time = 0
        max_time = 50000

        for index in range(len(shot_times)+1):
            # For the last laser trigger there is no next trigger, set ending to end of array
            try:
                timing = shot_times[index]
                slice_end_idx = np.searchsorted(ToA, timing, side='right')
            except:
                slice_end_idx = -1
            # The 1st index is data before the first trigger pulse
            if index == 0:
                start_idx = slice_end_idx
                continue
            # Get the times that correspond to the laser pulse
            times = np.copy(ToA[start_idx:slice_end_idx])
            # Ignore the loop of no data in it
            if len(times) == 0: continue
            # Set time to be relative for each pulse
            times -= np.min(times)
            # Remove laser pulse data and noise outside of thresholds
            not_noise = np.where((min_time < times) & (times < max_time))[0]
            if len(not_noise) == 0: continue
            # x_data.append(x[start_idx:slice_end_idx][not_noise])
            # y_data.append(y[start_idx:slice_end_idx][not_noise])
            # ToT_data.append(ToT[start_idx:slice_end_idx][not_noise])
            temp_toa = times[not_noise]
            toa_counts, toa_times = np.unique(temp_toa, return_counts=True)
            for index, ut in enumerate(toa_times):
                if ut not in ToA_data:
                    ToA_data[ut] = toa_counts[index]
                else:
                    ToA_data[ut] += toa_counts[index]
            start_idx = slice_end_idx
        x_toa = np.array([ToA_data[x] for x in ToA_data])
        y_toa = np.array([x for x in ToA_data])
        toa_array = np.vstack((x_toa, y_toa)).T
        toa_array = toa_array[toa_array[:, 0].argsort()]
        self.toa_spectrum_signal.emit(toa_array)

    def run(self) -> None:
        '''Ask the camera for image arrays.'''
        if self.saving:
            self.create_savefile()
        # self.device.doSensorRefresh()
        self.start_time = time.time()
        self.device.registerEvent(pixet.PX_EVENT_ACQ_NEW_DATA, 0, self.new_data)
        rc = self.device.doAdvancedAcquisition(self.iter, self.run_time, pixet.PX_ACQTYPE_DATADRIVEN, pixet.PX_ACQMODE_NORMAL, pixet.PX_FTYPE_AUTODETECT, 0, "")
        self.device.unregisterEvent(pixet.PX_EVENT_ACQ_NEW_DATA, 0, self.new_data)
        self.finished.emit()

    def stop(self) -> None:
        '''Stop the current acquisition.'''
        if self.device.isAcquisitionRunning():
            self.device.abortOperation()

#########################################################################################
# Class used for modifying the plots
#########################################################################################
class UI_Plots():
    def __init__(self, main_window):
        self.window_ = main_window
        self.generate_plots()
    
    def generate_plots(self):
        '''
        Setup plot for TOF data \n
        Plot only updates the data and does not redraw each update.\n
        Axes are updated by looking at value changes.\n
        '''
        # Create size policy for image plots
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)

        # Setup ToT variables
        self.window_.ToT_origpos_ = self.window_._ToT.pos()
        self.window_.ToT_origwidth_ = self.window_._ToT.width()
        self.window_.ToT_origheight_ = self.window_._ToT.height()
        self.window_._ToT.setWindowTitle('ToT')
        self.window_._ToT.installEventFilter(self.window_)
        # Create ToT plot
        self.window_.ToT_view_ = RawImageWidget(self.window_._ToT,scaled=True)
        self.grid = QtWidgets.QGridLayout(self.window_._ToT)
        self.grid.addWidget(self.window_.ToT_view_, 0, 0, 1, 1)
        self.window_.ToT_view_.setSizePolicy(sizePolicy)
        self.window_.ToT_view_.setImage(self.window_.tot_, levels=[0,255])

        # Setup ToA variables
        self.window_.ToA_origpos_ = self.window_._ToA.pos()
        self.window_.ToA_origwidth_ = self.window_._ToA.width()
        self.window_.ToA_origheight_ = self.window_._ToA.height()
        self.window_._ToA.setWindowTitle('ToA')
        self.window_._ToA.installEventFilter(self.window_)
        # Create ToA plot
        self.window_.ToA_view_ = RawImageWidget(self.window_._ToA,scaled=True)
        self.grid = QtWidgets.QGridLayout(self.window_._ToA)
        self.grid.addWidget(self.window_.ToA_view_, 0, 0, 1, 1)
        self.window_.ToA_view_.setSizePolicy(sizePolicy)
        self.window_.ToA_view_.setImage(self.window_.toa_, levels=[0,255])

        # Create ToF Spectrum
        self.window_.tof_plot_origpos = self.window_._tof_plot.pos()
        self.window_.tof_plot_origwidth = self.window_._tof_plot.width()
        self.window_.tof_plot_origheight = self.window_._tof_plot.height()
        self.window_.tof_plot_line = self.window_._tof_plot.plot(self.window_.tof_,pen=pg.mkPen(color=(255, 0, 0)))
        self.window_.tof_selection_line_min = self.window_._tof_plot.plot(self.window_.tof_,pen=pg.mkPen(color=(0, 0, 0)))
        self.window_.tof_selection_line_max = self.window_._tof_plot.plot(self.window_.tof_,pen=pg.mkPen(color=(0, 0, 0)))
        self.window_._tof_plot.setWindowTitle('ToF Spectrum')
        self.window_._tof_plot.setBackground('w')
        self.window_._tof_plot.installEventFilter(self.window_)
        self.window_._tof_plot.setLabel('bottom', "Time (ns)")
        self.window_._tof_plot.setLabel('left', "Counts")

        self.change_axes()

    def plot_selection(self):
        '''Updates the selection of the ToF displayed on the plot.'''
        x = np.zeros(50001)
        x[self.window_._min_x.value()] = self.window_._max_y.value()
        x[self.window_._max_x.value()] = self.window_._max_y.value()
        self.window_.tof_selection_line_min.setData(x,pen=pg.mkPen(color=(0, 0, 0), style=QtCore.Qt.PenStyle.DotLine))
        self.window_.tof_selection_line_max.setData(x,pen=pg.mkPen(color=(0, 0, 0), style=QtCore.Qt.PenStyle.DotLine))

    def change_axes(self):
        '''
        Updates the TOF axes to make it easier to view data.
        '''
        self.window_._tof_plot.setXRange(self.window_._tof_range_min.value(), self.window_._tof_range_max.value(), padding=0)
        self.window_._tof_plot.setYRange(self.window_._min_y.value(), self.window_._max_y.value(), padding=0)
        self.plot_selection()

    def rotate_camera(self,option):       
        #Rotate clockwise
        if option == 0:
            self.window_.rotation_ += 1
            if self.window_.rotation_ == 4: self.window_.rotation_ = 0
        #Rotate counter clockwise
        else:
            self.window_.rotation_ -= 1
            if self.window_.rotation_ < 0: self.window_.rotation_ = 3

    def pop_out_window(self,option):
        if option == 0:
            self.window_.tof_expanded_ = True
            self.window_._tof_plot.setParent(None)
            self.window_._tof_plot.move(int(self.window_.width()/2),int(self.window_.height()/2))
            self.window_._tof_plot.show()
        elif option == 1: 
            self.window_.toa_expanded_ = True
            self.window_._ToA.setParent(None)
            self.window_._ToA.move(int(self.window_.width()/2),int(self.window_.height()/2))
            self.window_._ToA.show()
        else:
            self.window_.tot_expanded_ = True
            self.window_._ToT.setParent(None)
            self.window_._ToT.move(int(self.window_.width()/2),int(self.window_.height()/2))
            self.window_._ToT.show()

#########################################################################################
# Mainwindow used for displaying UI
#########################################################################################
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super(MainWindow, self).__init__()

        # Load UI file
        self.scriptDir = os.path.dirname(__file__)
        uic.loadUi(f'{self.scriptDir}/PyPix.ui',self)

        # Add colourmaps
        colourmaps = pg.colormap.listMaps("matplotlib")
        self._colourmap.addItems(colourmaps)
        
        self.device = None   # Stores the connected device
        self.running = False # Store the state of the camera

        # Setup various plot variables in UI
        self.tof_ = np.zeros(50001)      # Show 50 uS of ToF Data
        self.tot_ = np.zeros((256,256)) # Image array for ToT Data
        self.toa_ = np.zeros((256,256)) # Image array for ToA Data
        self.tof_expanded_ = False      # Is the ToF Spectrum popped out?
        self.toa_expanded_ = False      # Is the ToA Image popped out?
        self.tot_expanded_ = False      # Is the ToT Image popped out?
        self.rotation_     = 0          # Rotation angle of the image

        #Call the class responsible for plot drawing and functions
        self.ui_plots = UI_Plots(self)

        # Link the pop-out buttons to the respective plots
        self._pop_tof.clicked.connect(lambda: self.ui_plots.pop_out_window(0))
        self._pop_toa.clicked.connect(lambda: self.ui_plots.pop_out_window(1))
        self._pop_tot.clicked.connect(lambda: self.ui_plots.pop_out_window(2))

        # Connect to camera
        self._camera_connect_button.clicked.connect(self.camera_connect)
        self._button.clicked.connect(self.start_acquisition)

        # Adjust ToF Spectrum
        self._tof_range_min.valueChanged.connect(self.ui_plots.change_axes)
        self._tof_range_max.valueChanged.connect(self.ui_plots.change_axes)
        self._min_y.valueChanged.connect(self.ui_plots.change_axes)
        self._max_y.valueChanged.connect(self.ui_plots.change_axes)
        self._min_x.valueChanged.connect(self.ui_plots.plot_selection)
        self._max_x.valueChanged.connect(self.ui_plots.plot_selection)

    def update_pb(self, value : list) -> None:
        '''Set the progressbar value'''
        self._progressBar.setValue(value[0])
        self._progressBar.setFormat(value[1])
        self.camera_temperature()

    def update_tot(self, value : list) -> None:
        image = value[0]
        led = value[1]
        radius = 15
        try: maximum = np.max(image[led[0]-radius:led[0]+radius,led[1]-radius:led[1]+radius]) # Get the maximum value of the led pixels
        except ValueError: maximum = np.max(image)
        colourmap = self._colourmap.currentText()
        if colourmap != "None": 
            cm = pg.colormap.get(colourmap,source="matplotlib")
            image = cm.map(image)
        else:
            image = np.array((image / maximum) * 255, dtype=int)
            overflow = np.where(image > 255)
            image[overflow] = 255
        if type(led[0]) != False:
            x1 = np.array([[led[0] - radius, led[1] - c] for c in range(-radius,radius+1)])
            y1 = np.array([[led[0] - c, led[1] - radius] for c in range(-radius,radius+1)])
            x2 = np.array([[led[0] + radius, led[1] - c] for c in range(-radius,radius+1)])
            y2 = np.array([[led[0] - c, led[1] + radius] for c in range(-radius,radius+1)])
            square = np.vstack((x1,y1,x2,y2))
            image[square[:,0], square[:,1]] = 255
        self.ToT_view_.setImage(image, levels=[0,255])

    def update_toa_spectrum(self, value: list) -> None:
        self.tof_plot_line.setData(value)

    def update_plots(self, value : list) -> None:
        image = self.image_
        
        # Scale the image based off the slider
        if self._vmax.value() != 100:
            image[image > (self._vmax.value()*0.01)] = 0
            image = ((image / np.max(image)))

        colourmap = self._colourmap.currentText()
        if colourmap != "None": 
            cm = pg.colormap.get(colourmap,source="matplotlib")
            image = cm.map(image)
        else:
            image = np.array(image * 255, dtype=np.uint8)

        self.ion_count_plot_line.setData(self.ion_counts_)
        self.tof_plot_line.setData(self.tof_counts_)
        self.graphics_view_.setImage(image, levels=[0,255])
        self._ion_count.setText(str(self.ion_count_displayed))

    def update_console(self,string : str) -> None:
        '''
        Update console log with result of command passed to PIMMS.
        '''
        if 'Error' in string:
            self.error_ = True
            self._plainTextEdit.setPlainText(string)
            self._plainTextEdit.setStyleSheet(
                """QPlainTextEdit {color: #FF0000;}"""
            )
            error = QtWidgets.QMessageBox()
            error.setText(string)
            error.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
            error = error.exec()
        else:
            self._plainTextEdit.setPlainText(string)
            self._plainTextEdit.setStyleSheet(
                """QPlainTextEdit {color: #000000;}"""
            )

    def open_file_dialog(self) -> None:
        '''Open the window for finding file'''
        file_path = QtWidgets.QFileDialog.getOpenFileName(
            parent=self,
            caption="Open File",
            directory=os.getenv("HOME")
        )
        self._trim_dir.setText(file_path[0])

    def eventFilter(self, source, event):
        '''
        Capture close events to pop the windows back into the main body
        '''
        if (event.type() == QtCore.QEvent.Type.Close and isinstance(source, QtWidgets.QWidget)):
            if source.windowTitle() == self._tof_plot.windowTitle():
                self.tof_expanded_ = False
                self._tof_plot.setParent(self._tab)
                self._tof_plot.setGeometry(
                    self.tof_plot_origpos.x(),
                    self.tof_plot_origpos.y(),
                    self.tof_plot_origwidth,
                    self.tof_plot_origheight
                )
                self._tof_plot.show()
            elif source.windowTitle() == self._ToT.windowTitle():
                self.tot_expanded_ = False
                self._ToT.setParent(self._tab)
                self._ToT.setGeometry(
                    self.ToT_origpos_.x(),
                    self.ToT_origpos_.y(),
                    self.ToT_origwidth_,
                    self.ToT_origheight_
                )
                self._ToT.show()
            else:
                self.toa_expanded_ = False
                self._ToA.setParent(self._tab)
                self._ToA.setGeometry(
                    self.ToA_origpos_.x(),
                    self.ToA_origpos_.y(),
                    self.ToA_origwidth_,
                    self.ToA_origheight_
                )
                self._ToA.show()                       
            event.ignore() #Ignore close
            return True #Tell qt that process done
        else:
            return super(MainWindow,self).eventFilter(source,event)
        
    def camera_connect(self):
        devices = pixet.devicesByType(pixet.PX_DEVTYPE_TPX3)
        if len(devices) == 0:
            self.update_console('Error, cannot connect to camera!')
            self.device = None
            return
        self.device = devices[0]
        self.update_console('Connected to Timepix3 Camera!')
        self.camera_temperature()
        # After connecting, update device using config file.
        config_file = f'{self.scriptDir}/{self._trim_dir.text()}'
        if not os.path.isfile(config_file):
            self.update_console(f'Error, cannot find config file: {config_file}')
            return
        self.device.loadConfigFromFile(config_file)
        self.device.setBias(bias)
        self.device.setOperationMode(pixet.PX_TPX3_OPM_TOATOT)
        self.update_console(f'Set configuration using: {self._trim_dir.text()}\n')
        self._button.setEnabled(True)
        self._camera_connect_button.setEnabled(False)

    def start_acquisition(self) -> None:
        if self.running:
            self._button.setEnabled(False)
            self.acquisition_thread.stop()
        else:
            thread = ImageAcquisitionThread(self)
            thread.progress.connect(self.update_pb)
            thread.tot_signal.connect(self.update_tot)
            thread.toa_spectrum_signal.connect(self.update_toa_spectrum)
            thread.finished.connect(self.camera_finished)
            self.acquisition_thread = thread
            self.acquisition_thread.start()
            self.running = True
            self._button.setText("Stop")

    def camera_finished(self) -> None:
        self.running = False
        self._button.setText("Start")
        self.acquisition_thread.wait()
        del self.acquisition_thread
        self._button.setEnabled(True)

    def camera_temperature(self) -> None:
        parameters = self.device.parameters()
        tchip = round(parameters.get("TemperatureChip").getDouble(),2)
        self._sensor_temp.setText(f'{tchip} C')

def except_hook(error, exception, traceback):
    '''If this is not called the UI will not return errors'''
    sys.__excepthook__(error, exception, traceback)

if __name__ == '__main__':
    sys.excepthook = except_hook
    app = QtWidgets.QApplication(sys.argv)

    #Create window
    w = MainWindow()
    #Load the app
    w.show()

    app.exec()

pixet.exitPixet()