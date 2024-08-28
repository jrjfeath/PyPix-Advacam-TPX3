/**
 * Copyright (C) 2018 ADVACAM
 * @author    Daniel Turecek <daniel.turecek@advacam.com>
 */
#include "pxcapi.h"
#include <cstring>
#include <algorithm>

#define SINGLE_CHIP_PIXSIZE      65536
#define ERRMSG_BUFF_SIZE         512
#define PIXEL_BUFF_LEN           1000000



int printError(const char* errorPrefix)
{
    char errorMsg[ERRMSG_BUFF_SIZE];
    pxcGetLastError(errorMsg, ERRMSG_BUFF_SIZE);
    printf("%s: %s\n", errorPrefix, errorMsg);
    return -1;
}

// ############################################## Timepix Examples ############################################33

int singleMeasurementTest(unsigned deviceIndex)
{
    // Measure one frame and get its data
    unsigned short frameData[SINGLE_CHIP_PIXSIZE];
    unsigned frameSize = SINGLE_CHIP_PIXSIZE;
    int rc = pxcMeasureSingleFrame(deviceIndex, 0.1, frameData, &frameSize);
    if (rc)
        return printError("Could not measure frame");
    return 0;
}

void measurementCallback(intptr_t acqCount, intptr_t userData)
{
    unsigned devIndex = *((unsigned*)userData);
    printf("Measured frame %lu\n", acqCount - 1);
    printf("Measured frame count: %d\n", pxcGetMeasuredFrameCount(devIndex));

    unsigned short frameData[SINGLE_CHIP_PIXSIZE];
    unsigned frameSize = SINGLE_CHIP_PIXSIZE;
    pxcGetMeasuredFrame(devIndex, (unsigned)acqCount - 1, frameData, &frameSize);
}

int multipleMeasurementTestWithCallback(unsigned deviceIndex)
{
    double frameTime = 0.001;
    unsigned frameCount = 100;

    // Measure multiple frames and receive callback after each measured frame
    int devIdx = deviceIndex;
    int rc = pxcMeasureMultipleFramesWithCallback(deviceIndex, frameCount, frameTime, PXC_TRG_NO, measurementCallback, (intptr_t)&devIdx);
    if (rc)
        return printError("Could not measure frames");
    return 0;
}


// ############################################## Timepix3 Examples ############################################33

#define PAR_DDBLOCKSIZE         "DDBlockSize"
#define PAR_DDBUFFSIZE          "DDBuffSize"
#define PAR_DUMMYSPEED          "DDDummyDataSpeed"
#define PAR_BLOCKCOUNT          "BlockCount"
#define PAR_PROCESSDATA         "ProcessData"
#define PAR_TRG_STG             "TrgStg"

Tpx3Pixel* gPixels;

void onTpx3Data(intptr_t eventData, intptr_t userData)
{
    int deviceIndex = userData;
    unsigned pixelCount = 0;
    int rc = pxcGetMeasuredTpx3PixelsCount(deviceIndex, &pixelCount);
    printf("(rc= %d, eventData=%lu) PixelCount: %u\n", rc, eventData, pixelCount);

    if (rc) {
        printError("");
        return;
    }

    rc = pxcGetMeasuredTpx3Pixels(deviceIndex, gPixels, std::min(pixelCount, (unsigned)PIXEL_BUFF_LEN));
    if (rc) {
        printError("");
        return;
    }

    for (unsigned i = 0; i < std::min(pixelCount, (unsigned)30); i++){
        printf("Pixel: [Index=%d, ToT=%f, Toa=%f] \n", gPixels[i].index, gPixels[i].tot, gPixels[i].toa);
    }
}


void timepix3DataDrivenGetPixelsTest(unsigned deviceIndex)
{
    gPixels = new Tpx3Pixel[PIXEL_BUFF_LEN];
    pxcMeasureTpx3DataDrivenMode(deviceIndex, 5, "", PXC_TRG_NO, onTpx3Data, (intptr_t)deviceIndex);
    delete[] gPixels;
}


void timepix3DataDrivenToFileTest(unsigned deviceIndex)
{
    // set the block and buffer size
    //pxcSetDeviceParameter(deviceIndex, PAR_DDBLOCKSIZE, 10); // in MB
    //pxcSetDeviceParameter(deviceIndex, PAR_DDBUFFSIZE, 500); // in MB
    //pxcSetDeviceParameter(deviceIndex, PAR_TRG_STG, 3); // (0=logical 0, 1 = logical 1, 2 = rising edge, 3 = falling edge)

    //pxcMeasureTpx3DataDrivenMode(deviceIndex, 5, "test.t3r", PXC_TRG_NO, 0, 0);
    //pxcMeasureTpx3DataDrivenMode(deviceIndex, 5, "test.t3pa", PXC_TRG_HWSTART, 0, 0); // measurement with trigger
    pxcMeasureTpx3DataDrivenMode(deviceIndex, 5, "test.t3pa", PXC_TRG_NO, 0, 0);
}


int main (int argc, char const* argv[])
{
    // Initialize Pixet
    int rc = pxcInitialize();
    if (rc)
        return printError("Could not initialize Pixet");

    int connectedDevicesCount = pxcGetDevicesCount();
    printf("Connected devices: %d\n", connectedDevicesCount);

    if (connectedDevicesCount == 0)
        return pxcExit();

    // list all connected devices (name + chipID)
    for (unsigned devIdx = 0; devIdx < connectedDevicesCount; devIdx++){
        char deviceName[256];
        memset(deviceName, 0, 256);
        pxcGetDeviceName(devIdx, deviceName, 256);

        char chipID[256];
        memset(chipID, 0, 256);
        pxcGetDeviceChipID(0, 0, chipID, 256);

        printf("Device %d Name %s, (ChipID: %s)\n", devIdx, deviceName, chipID);
    }

    // Different Example Measurements:

    //singleMeasurementTest(0);
    //multipleMeasurementTestWithCallback(0);
    //timepix3DataDrivenGetPixelsTest(0);
    timepix3DataDrivenToFileTest(0);


    // Exit Pixet
    return pxcExit();
}
