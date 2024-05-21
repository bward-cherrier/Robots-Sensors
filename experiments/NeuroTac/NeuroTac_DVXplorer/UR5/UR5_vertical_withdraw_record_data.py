# -*- coding: utf-8 -*-

import pickle
import time, os, json, math
import threading

from cri.robot import SyncRobot, AsyncRobot
from cri.controller import RTDEController

from vsp.video_stream import CvVideoDisplay, CvVideoOutputFile
from vsp.processor import AsyncProcessor, CameraStreamProcessorMP

from core.sensor.tactile_capture_timestamp import CameraStreamProcessorMPTimestamp, CaptureTimestamp
from core.sensor.tactile_sensor_neuro import NeuroTac_DVXplorer
from core.sensor.ft_sensor import FTSensorSerial, AsyncFTSensorSerial

def make_meta(robot_tcp = [0, 0, 118.5, 0, 0, 70],
              base_frame = [0, 0, 0, 0, 0, 0],
              home_pose = [109.1, -456.0, 340.0, 180, 0, -160],
              work_frame = [271.5, -462, 85, 180, 90, -160], # [268, -462, 85, 180, 90, 180] for thickness 10 mm, [272, -462, 85, 180, 90, 180] for thickness 5mm, [276, -462, 85, 180, 90, 180] for thickness 2mm
              linear_speed = 20,
              angular_speed = 10,
              slide_speeds = [0.3,0.5,1.0]  ,  # [0.3, 0.5, 1.0]  
              slide_depths = [3,4,5],  # [3,4,5]
              slide_directions = ['back'], # ['right','left','down','up','upright','upleft','downright','downleft']
              n_runs = 1,
              sensor_type = 'IncUndExt_v1'
              ):

    meta = locals().copy()
    return meta

# UR5 Controller
def make_robot():
    return AsyncRobot(SyncRobot(RTDEController(ip='192.11.72.10')))

# Camera recording inside the tactip
def make_sensor_in():  
    return NeuroTac_DVXplorer(port=43195)


# Camera recording outside the tactip     
def make_sensor_out(video_dir, device_path="/dev/video5", display=CvVideoDisplay(name='tactip_out'), frame_size=(640, 480), fps=60, cut=(0, 0)):
    return AsyncProcessor(CameraStreamProcessorMPTimestamp(
        camera=CaptureTimestamp(device_path=device_path, frame_size=frame_size, num_buffers=1, cut=cut, is_color=True, exposure = 90),
        display=display,
        writer=CvVideoOutputFile(filename=os.path.join(video_dir, 'tactip_out.mp4'), fps=fps,
                                 is_color=True, fourcc_code='mp4v', frame_size=(640, 480))
    ))

# Robotiq FT sensor
def make_sensor_ft():
    sensor = FTSensorSerial()
    return AsyncFTSensorSerial(sync_sensor = sensor)

def collect(collect_dir, video_dir, events_dir, robot_tcp, base_frame, home_pose, work_frame, linear_speed, angular_speed, \
    slide_depths, slide_speeds, slide_directions, n_runs, **kwargs):

    ts_data_out = os.path.join(collect_dir, 'timestamps_tactip_out.pkl')
    ts_data_in = os.path.join(collect_dir, 'timestamps_tactip_in.pkl')
    # ft_data = os.path.join(collect_dir, 'ft_data.pkl')

    with make_sensor_in() as sensor_in, make_sensor_out(video_dir, cut=None) as sensor_out, \
        make_robot() as robot, make_sensor_ft() as sensor_FT:

        # Set robot parameters
        robot.tcp = robot_tcp
        robot.linear_speed = linear_speed
        robot.angular_speed = angular_speed

        # Move home
        _ = robot.move_linear(home_pose)

         # Start sensor
        # sensor_in.process(num_frames=5)
        sensor_out.process(num_frames=5)

         # Move to origin of work frame
        print("Moving to origin of work frame ...")
        _ = robot.move_linear(work_frame) 

        ts_dict_out = {}
        ts_dict_in = {}
        FT_dict = {}
        for r in range(n_runs):
            for speed in slide_speeds:
                for depth in slide_depths:
                    for direction in slide_directions:
                        
                        # Reset FT sensor
                        # sensor_FT.set_zero_ref()
                        sensor_in.reset_variables()
                        
                             # Set robot positions
                        retract = 3
                        height = 60
                        ur5_positions = [[0,0,0,0,0,0],[10+depth,0,0,0,0,0],[10+depth,0,height,0,0,0],[10+depth-retract,0,height,0,0,0],[0,0,height,0,0,0]]
                        ur5_positions = [list(map(sum,zip(p, work_frame))) for p in ur5_positions]

                        # Move to starting point
                        print("Moving to " + str(ur5_positions[0]))
                        _ = robot.move_linear(ur5_positions[0])
                        print('depth: ' + str(depth) + ', speed: ' + str(speed) + ', run: ' + str(r) + ', direction: ' + str(direction))

                        # Set output files
                        tactip_out_video = os.path.join(video_dir, 'tactip_out_d'+ str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r)+'.mp4')
                        events_on_file = os.path.join(events_dir,'d' + str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r)+'_events_on.pickle')
                        events_off_file = os.path.join(events_dir,'d' + str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r)+'_events_off.pickle')
                        # ft_sensor_data = os.path.join(collect_dir, 'ft_sensor_d'+ str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r)+'.pkl')

                        # Check depth is safe
                        if depth > 6:
                            raise Exception("Risk of damaging tactip...quitting")

                        # Contact perspex
                        robot.linear_speed = 4
                        _ = robot.move_linear(ur5_positions[1])  # Contact object
                        _ = robot.move_linear(ur5_positions[2]) # Lift object up

                        # Start sensors
                        sensor_out.async_process(outfile=tactip_out_video, num_frames=5000)  # Start exterior cam rec
                        sensor_in.start_logging()
                        t = threading.Thread(target=sensor_in.get_pixel_events, args = ())
                        t.start()
                        # sensor_FT.async_read(num_frames = 5000)
                        
                        time.sleep(1)

                        # Start moving back
                        robot.linear_speed = speed
                        _ = robot.move_linear(ur5_positions[3])
                        
                        # Stop recording
                        sensor_in.stop_logging()
                        t.join()
                        sensor_out.async_cancel()

                        # Write videos and timestamps to file
                        _, ts_out = sensor_out.async_result()
                                # Save data

                        sensor_in.value_cleanup()
                        sensor_in.save_events_on(events_on_file)
                        sensor_in.save_events_off(events_off_file)

                        # Stop FT sensor
                        # sensor_FT.async_cancel()
                        # _ = sensor_FT.async_result()

                        # Update timestamps and FT values
                        ts_dict_out.update({'tactip_out_d'+ str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r): ts_out})
                        # ts_dict_in.update({'tactip_in_d' + str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r): ts_in})
                        # FT_dict.update = ({'tactip_in_d' + str(depth) + '_s' + str(speed) + '_dir_' + direction + '_r' + str(r): ts_in})
                        ts_out = None
                        # ts_in = None        
                        ft = None

                        # Move back from perspex
                        robot.linear_speed = linear_speed
                        _ = robot.move_linear(ur5_positions[4])

        # Return home
        print("Moving home ...")
        robot.linear_speed = linear_speed
        robot.move_linear(home_pose)  # Move home

        # Save timestamp data
        with open(ts_data_out, 'wb') as t:
            pickle.dump(ts_dict_out, t)
        with open(ts_data_in, 'wb') as t:
            pickle.dump(ts_dict_in, t)
        # with open(ft_data, 'wb') as f:
        #     pickle.dump(FT_dict, f)
        
def main():

    # Directories
    collect_dir_name = os.path.join('vertical_withdraw', 'vertical_withdraw_' + time.strftime('%m%d%H%M'))
    collect_dir = os.path.join(os.environ['DATAPATH'], 'NeuroTac_DVXplorer', collect_dir_name)
    video_dir = os.path.join(collect_dir, 'videos')
    events_dir = os.path.join(collect_dir, 'events')
    
    os.makedirs(collect_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(events_dir, exist_ok=True)

    # Make and save meta data and dataframe
    meta = make_meta() 
    with open(os.path.join(collect_dir, 'meta.json'), 'w') as f:
        json.dump(meta, f) 

    # Collect data
    collect(collect_dir,video_dir,events_dir,**meta)

if __name__ == '__main__':
    main()
