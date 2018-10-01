'''Contains the Camera accessory and related.
'''

import os
import ipaddress
import logging
import struct
import subprocess

from pyhap import RESOURCE_DIR
from pyhap.accessory import Accessory
from pyhap import loader
from pyhap import tlv
from pyhap.util import toBase64Str, base64ToBytes


logger = logging.getLogger(__name__)


SETUP_TYPES = {
    'SESSION_ID': b'\x01',
    'STATUS': b'\x02',
    'ADDRESS': b'\x03',
    'VIDEO_SRTP_PARAM': b'\x04',
    'AUDIO_SRTP_PARAM': b'\x05',
    'VIDEO_SSRC': b'\x06',
    'AUDIO_SSRC': b'\x07'
}


SETUP_STATUS = {
    'SUCCESS': b'\x00',
    'BUSY': b'\x01',
    'ERROR': b'\x02'
}


SETUP_IPV = {
    'IPV4': b'\x00',
    'IPV6': b'\x01'
}


SETUP_ADDR_INFO = {
    'ADDRESS_VER': b'\x01',
    'ADDRESS': b'\x02',
    'VIDEO_RTP_PORT': b'\x03',
    'AUDIO_RTP_PORT': b'\x04'
}


SETUP_SRTP_PARAM = {
    'CRYPTO': b'\x01',
    'MASTER_KEY': b'\x02',
    'MASTER_SALT': b'\x03'
}


STREAMING_STATUS = {
    'AVAILABLE': b'\x00',
    'STREAMING': b'\x01',
    'BUSY': b'\x02'
}


RTP_CONFIG_TYPES = {
    'CRYPTO': b'\x02'
}


SRTP_CRYPTO_SUITES = {
    'AES_CM_128_HMAC_SHA1_80': b'\x00',
    'AES_CM_256_HMAC_SHA1_80': b'\x01',
    'NONE': b'\x02'
}


VIDEO_TYPES = {
    'CODEC': b'\x01',
    'CODEC_PARAM': b'\x02',
    'ATTRIBUTES': b'\x03',
    'RTP_PARAM': b'\x04'
}


VIDEO_CODEC_TYPES = {
    'H264': b'\x00'
}


VIDEO_CODEC_PARAM_TYPES = {
    'PROFILE_ID': b'\x01',
    'LEVEL': b'\x02',
    'PACKETIZATION_MODE': b'\x03',
    'CVO_ENABLED': b'\x04',
    'CVO_ID': b'\x05'
}


VIDEO_CODEC_PARAM_CVO_TYPES = {
    'UNSUPPORTED': b'\x01',
    'SUPPORTED': b'\x02'
}


VIDEO_CODEC_PARAM_PROFILE_ID_TYPES = {
    'BASELINE': b'\x00',
    'MAIN': b'\x01',
    'HIGH': b'\x02'
}


VIDEO_CODEC_PARAM_LEVEL_TYPES = {
    'TYPE3_1': b'\x00',
    'TYPE3_2': b'\x01',
    'TYPE4_0': b'\x02'
}


VIDEO_CODEC_PARAM_PACKETIZATION_MODE_TYPES = {
    'NON_INTERLEAVED': b'\x00'
}


VIDEO_ATTRIBUTES_TYPES = {
    'IMAGE_WIDTH': b'\x01',
    'IMAGE_HEIGHT': b'\x02',
    'FRAME_RATE': b'\x03'
}


SELECTED_STREAM_CONFIGURATION_TYPES = {
    'SESSION': b'\x01',
    'VIDEO': b'\x02',
    'AUDIO': b'\x03'
}


RTP_PARAM_TYPES = {
    'PAYLOAD_TYPE': b'\x01',
    'SYNCHRONIZATION_SOURCE': b'\x02',
    'MAX_BIT_RATE': b'\x03',
    'RTCP_SEND_INTERVAL': b'\x04',
    'MAX_MTU': b'\x05',
    'COMFORT_NOISE_PAYLOAD_TYPE': b'\x06'
}


AUDIO_TYPES = {
    'CODEC': b'\x01',
    'CODEC_PARAM': b'\x02',
    'RTP_PARAM': b'\x03',
    'COMFORT_NOISE': b'\x04'
}


AUDIO_CODEC_TYPES = {
    'PCMU': b'\x00',
    'PCMA': b'\x01',
    'AACELD': b'\x02',
    'OPUS': b'\x03'
}


AUDIO_CODEC_PARAM_TYPES = {
    'CHANNEL': b'\x01',
    'BIT_RATE': b'\x02',
    'SAMPLE_RATE': b'\x03',
    'PACKET_TIME': b'\x04'
}


AUDIO_CODEC_PARAM_BIT_RATE_TYPES = {
    'VARIABLE': b'\x00',
    'CONSTANT': b'\x01'
}


AUDIO_CODEC_PARAM_SAMPLE_RATE_TYPES = {
    'KHZ_8': b'\x00',
    'KHZ_16': b'\x01',
    'KHZ_24': b'\x02'
}


SESSION_ID = b'\x01'

class CameraAccessory(Accessory):
    '''An Accessory that can negotiated camera stream settings with iOS and start a
    stream.
    '''

    NO_SRTP = b'\x01\x01\x02\x02\x00\x03\x00'
    '''Configuration value for no SRTP.'''

    FFMPEG_CMD = ('ffmpeg -f video4linux2 -input_format h264 -video_size {width}x{height} -framerate 20 -i /dev/video0 '
        '-vcodec copy -an -payload_type 99 -ssrc 1 -f rtsp '
        '-b:v {bitrate}k -bufsize {bitrate}k '
        '-payload_type 99 -f rtp '
        '-srtp_out_suite AES_CM_128_HMAC_SHA1_80 -srtp_out_params {video_srtp_key} '
        'srtp://{address}:{video_port}?rtcpport={video_port}&'
        'localrtcpport={local_video_port}&pkt_size=1378')
    '''Template for the ffmpeg command.'''

    @staticmethod
    def get_supported_rtp_config(support_srtp):
        '''XXX
        :param support_srtp: True if SRTP is supported, False otherwise.
        :type support_srtp: bool
        '''
        if support_srtp:
            crypto = SRTP_CRYPTO_SUITES['AES_CM_128_HMAC_SHA1_80']
        else:
            crypto = SRTP_CRYPTO_SUITES['NONE']
        return toBase64Str(
                tlv.encode(RTP_CONFIG_TYPES['CRYPTO'], crypto))

    @staticmethod
    def get_supported_video_stream_config(video_params):
        '''XXX
        Expected video parameters:
            - codec
            - resolutions
        '''
        codec_params_tlv = tlv.encode(
            VIDEO_CODEC_PARAM_TYPES['PACKETIZATION_MODE'],
            VIDEO_CODEC_PARAM_PACKETIZATION_MODE_TYPES['NON_INTERLEAVED'])

        codec_params = video_params['codec']
        for profile in codec_params['profiles']:
            codec_params_tlv += \
                tlv.encode(VIDEO_CODEC_PARAM_TYPES['PROFILE_ID'], profile)

        for level in codec_params['levels']:
            codec_params_tlv += \
                tlv.encode(VIDEO_CODEC_PARAM_TYPES['LEVEL'], level)

        attr_tlv = b''
        for resolution in video_params['resolutions']:
            res_tlv = tlv.encode(
                VIDEO_ATTRIBUTES_TYPES['IMAGE_WIDTH'], struct.pack('<H', resolution[0]),
                VIDEO_ATTRIBUTES_TYPES['IMAGE_HEIGHT'], struct.pack('<H', resolution[1]),
                VIDEO_ATTRIBUTES_TYPES['FRAME_RATE'], struct.pack('<H', resolution[2]))
            attr_tlv += tlv.encode(VIDEO_TYPES['ATTRIBUTES'], res_tlv)

        config_tlv = tlv.encode(VIDEO_TYPES['CODEC'], VIDEO_CODEC_TYPES['H264'],
                                VIDEO_TYPES['CODEC_PARAM'], codec_params_tlv)

        return toBase64Str(
                tlv.encode(b'\x01', config_tlv + attr_tlv))

    @staticmethod
    def get_supported_audio_stream_config(audio_params):
        '''XXX
        iOS supports only AACELD and OPUS

        Expected audio parameters:
        - codecs
        - comfort_noise
        '''
        has_supported_codec = False
        configs = b''
        for codec_param in audio_params['codecs']:
            param_type = codec_param['type']
            if param_type == 'OPUS':
                has_supported_codec = True
                codec = AUDIO_CODEC_TYPES['OPUS']
                bitrate = AUDIO_CODEC_PARAM_BIT_RATE_TYPES['VARIABLE']
            elif param_type == 'AAC-eld':
                has_supported_codec = True
                codec = AUDIO_CODEC_TYPES['AACELD']
                bitrate = AUDIO_CODEC_PARAM_BIT_RATE_TYPES['VARIABLE']
            else:
                logger.warning('Unsupported codec %s', param_type)
                continue

            param_samplerate = codec_param['samplerate']
            if param_samplerate == 8:
                samplerate = AUDIO_CODEC_PARAM_SAMPLE_RATE_TYPES['KHZ_8']
            elif param_samplerate == 16:
                samplerate = AUDIO_CODEC_PARAM_SAMPLE_RATE_TYPES['KHZ_16']
            elif param_samplerate == 24:
                samplerate = AUDIO_CODEC_PARAM_SAMPLE_RATE_TYPES['KHZ_24']
            else:
                logger.warning('Unsupported sample rate %s', param_samplerate)
                continue

            param_tlv = tlv.encode(AUDIO_CODEC_PARAM_TYPES['CHANNEL'], b'\x01',
                                   AUDIO_CODEC_PARAM_TYPES['BIT_RATE'], bitrate,
                                   AUDIO_CODEC_PARAM_TYPES['SAMPLE_RATE'], samplerate)
            config_tlv = tlv.encode(AUDIO_TYPES['CODEC'], codec,
                                    AUDIO_TYPES['CODEC_PARAM'], param_tlv)
            configs += tlv.encode(b'\x01', config_tlv)

        if not has_supported_codec:
            logger.warning('Client does not support any audio codec that iOS supports.')

            codec = AUDIO_CODEC_TYPES['OPUS']
            bitrate = AUDIO_CODEC_PARAM_BIT_RATE_TYPES['VARIABLE']
            samplerate = AUDIO_CODEC_PARAM_SAMPLE_RATE_TYPES['KHZ_24']

            param_tlv = tlv.encode(
                AUDIO_CODEC_PARAM_TYPES['CHANNEL'], b'\x01',
                AUDIO_CODEC_PARAM_TYPES['BIT_RATE'], bitrate,
                AUDIO_CODEC_PARAM_TYPES['SAMPLE_RATE'], samplerate)

            config_tlv = tlv.encode(AUDIO_TYPES['CODEC'], codec,
                                    AUDIO_TYPES['CODEC_PARAM'], param_tlv)

            configs = tlv.encode(b'\x01', config_tlv)

        comfort_noise = b'\x01' if audio_params.get('comfort_noise', False) else b'\x00'
        audio_config = toBase64Str(
                        configs + tlv.encode(b'\x02', comfort_noise))
        return audio_config

    def __init__(self, options, *args, **kwargs):
        '''
        Expected options:
        - video
        - audio
        - srtp
        - address
        '''
        self.streaming_status = STREAMING_STATUS['AVAILABLE']
        self.support_srtp = options.get('srtp', False)
        self.supported_rtp_config = self.get_supported_rtp_config(self.support_srtp)
        self.supported_video_config = \
            self.get_supported_video_stream_config(options['video'])
        self.supported_audio_config = \
            self.get_supported_audio_stream_config(options['audio'])

        self.stream_address = options['address']
        try:
            ipaddress.IPv4Address(self.stream_address)
            self.stream_address_isv6 = b'\x00'
        except ValueError:
            self.stream_address_isv6 = b'\x01'
        self.sessions = {}
        self.selected_config = None
        self.setup_response = None
        self.session_id = None
        self.management_service = None

        super(CameraAccessory, self).__init__(*args, **kwargs)
        print(self.iid_manager.get_iid(self.management_service.get_characteristic('StreamingStatus')))
        print("Streaming status", self.management_service.get_characteristic('StreamingStatus'))
        print("Supported RTP config", self.management_service.get_characteristic('SupportedRTPConfiguration'))
        print("Supported video config", self.management_service.get_characteristic('SupportedVideoStreamConfiguration'))
        print("Supported audio config", self.management_service.get_characteristic('SupportedAudioStreamConfiguration'))

    def _set_services(self):
        '''
        '''
        super(CameraAccessory, self)._set_services()

        serv_loader = loader.get_serv_loader()

        self.management_service = serv_loader.get_service('CameraRTPStreamManagement')
        self.add_service(self.management_service)

        self.management_service.get_characteristic('StreamingStatus')\
                               .set_value(self._get_streaimg_status())

        self.management_service.get_characteristic('SupportedRTPConfiguration')\
                               .set_value(self.supported_rtp_config)

        self.management_service.get_characteristic('SupportedVideoStreamConfiguration')\
                               .set_value(self.supported_video_config)

        self.management_service.get_characteristic('SupportedAudioStreamConfiguration')\
                               .set_value(self.supported_audio_config)

        selected_stream = \
            self.management_service.get_characteristic('SelectedRTPStreamConfiguration')
        selected_stream.set_value(self.selected_config)
        selected_stream.setter_callback = self.set_selected_stream_configuration

        endpoints = self.management_service.get_characteristic('SetupEndpoints')
        endpoints.set_value(self.setup_response)
        endpoints.setter_callback = self.set_endpoints

        # microphone
        self.add_service(serv_loader.get_service('Microphone'))

    def _start_stream(self, objs, reconfigure):
        video_tlv = objs.get(SELECTED_STREAM_CONFIGURATION_TYPES['VIDEO'])
        audio_tlv = objs.get(SELECTED_STREAM_CONFIGURATION_TYPES['AUDIO'])

        if video_tlv:
            video_objs = tlv.decode(video_tlv)

            video_codec_params = video_objs.get(VIDEO_TYPES['CODEC_PARAM'])
            if video_codec_params:
                video_codec_param_objs = tlv.decode(video_codec_params)
                profile_id = \
                    video_codec_param_objs[VIDEO_CODEC_PARAM_TYPES['PROFILE_ID']]
                level = video_codec_param_objs[VIDEO_CODEC_PARAM_TYPES['LEVEL']]

            video_attrs = video_objs.get(VIDEO_TYPES['ATTRIBUTES'])
            if video_attrs:
                video_attr_objs = tlv.decode(video_attrs)
                width = struct.unpack('<H',
                            video_attr_objs[VIDEO_ATTRIBUTES_TYPES['IMAGE_WIDTH']])[0]
                height = struct.unpack('<H',
                            video_attr_objs[VIDEO_ATTRIBUTES_TYPES['IMAGE_HEIGHT']])[0]
                fps = struct.unpack('<B',
                                video_attr_objs[VIDEO_ATTRIBUTES_TYPES['FRAME_RATE']])[0]

            video_rtp_param = video_objs.get(VIDEO_TYPES['RTP_PARAM'])
            if video_rtp_param:
                video_rtp_param_objs = tlv.decode(video_rtp_param)
                #TODO: Optionals, handle the case where they are missing
                video_ssrc = 1 or struct.unpack('<I',
                    video_rtp_param_objs.get(
                        RTP_PARAM_TYPES['SYNCHRONIZATION_SOURCE']))[0]
                video_payload_type = \
                    video_rtp_param_objs.get(RTP_PARAM_TYPES['PAYLOAD_TYPE'])
                video_max_bitrate = struct.unpack('<H',
                    video_rtp_param_objs.get(RTP_PARAM_TYPES['MAX_BIT_RATE']))[0]
                video_rtcp_interval = \
                    video_rtp_param_objs.get(RTP_PARAM_TYPES['RTCP_SEND_INTERVAL'])
                video_max_mtu = video_rtp_param_objs.get(RTP_PARAM_TYPES['MAX_MTU'])

        if audio_tlv:
            audio_objs = tlv.decode(audio_tlv)
            audio_codec = audio_objs[AUDIO_TYPES['CODEC']]
            audio_codec_param_objs = tlv.decode(
                                        audio_objs[AUDIO_TYPES['CODEC_PARAM']])
            audio_rtp_param_objs = tlv.decode(
                                        audio_objs[AUDIO_TYPES['RTP_PARAM']])
            audio_comfort_noise = audio_objs[AUDIO_TYPES['COMFORT_NOISE']]

            # TODO handle audio codec
            audio_channel = audio_codec_param_objs[AUDIO_CODEC_PARAM_TYPES['CHANNEL']]
            audio_bitrate = audio_codec_param_objs[AUDIO_CODEC_PARAM_TYPES['BIT_RATE']]
            audio_sample_rate = \
                audio_codec_param_objs[AUDIO_CODEC_PARAM_TYPES['SAMPLE_RATE']]
            audio_packet_time = \
                audio_codec_param_objs[AUDIO_CODEC_PARAM_TYPES['PACKET_TIME']]

            audio_ssrc = audio_rtp_param_objs[RTP_PARAM_TYPES['SYNCHRONIZATION_SOURCE']]
            audio_payload_type = audio_rtp_param_objs[RTP_PARAM_TYPES['PAYLOAD_TYPE']]
            audio_max_bitrate = audio_rtp_param_objs[RTP_PARAM_TYPES['MAX_BIT_RATE']]
            audio_rtcp_interval = \
                audio_rtp_param_objs[RTP_PARAM_TYPES['RTCP_SEND_INTERVAL']]
            audio_comfort_payload_type = \
                audio_rtp_param_objs[RTP_PARAM_TYPES['COMFORT_NOISE_PAYLOAD_TYPE']]

        session_objs = tlv.decode(objs[SELECTED_STREAM_CONFIGURATION_TYPES['SESSION']])
        session_id = session_objs[b'\x01']
        session_info = self.sessions[session_id]
        width = width or 1280
        height = height or 720
        video_max_bitrate = video_max_bitrate or 300
        fps = min(fps, 30)

        cmd = self.FFMPEG_CMD.format(
            camera_source='0:0',
            address=session_info['address'],
            video_port=session_info['video_port'],
            video_srtp_key=toBase64Str(session_info['video_srtp_key']
                                       + session_info['video_srtp_salt']),
            video_ssrc=video_ssrc,  # TODO: this param is optional, check before adding
            fps=fps,
            width=width,
            height=height,
            bitrate=video_max_bitrate,
            local_video_port=session_info['video_port']
        ).split()

        logging.debug('Starting ffmpeg command: %s', cmd)
        print(" ".join(cmd))
        self.sessions[session_id]['process'] = subprocess.Popen(cmd)
        logging.debug('Started ffmpeg')
        self.streaming_status = STREAMING_STATUS['STREAMING']
        self.management_service.get_characteristic('StreamingStatus')\
                               .set_value(self._get_streaimg_status())

    def _get_streaimg_status(self):
        return toBase64Str(
                tlv.encode(b'\x01', self.streaming_status))

    def _stop_stream(self, objs):
        session_objs = tlv.decode(objs[SELECTED_STREAM_CONFIGURATION_TYPES['SESSION']])
        session_id = session_objs[b'\x01']
        ffmpeg_process = self.sessions.pop(session_id).get('process')
        if ffmpeg_process:
            ffmpeg_process.kill()
        self.session_id = None

    def set_selected_stream_configuration(self, value):
        '''XXX Called from iOS to select a stream configuration.
        '''
        logger.debug('set_selected_stream_config - value - %s', value)
        self.selected_config = value
        objs = tlv.decode(base64ToBytes(value))
        if SELECTED_STREAM_CONFIGURATION_TYPES['SESSION'] not in objs:
            logger.error('Bad request to set selected stream configuration.')
            return

        session = tlv.decode(objs[SELECTED_STREAM_CONFIGURATION_TYPES['SESSION']])

        request_type = session[b'\x02'][0]
        logging.debug('Set stream config request: %d', request_type)
        if request_type == 1:
            self._start_stream(objs, reconfigure=False)
        elif request_type == 0:
            self._stop_stream(objs)
        elif request_type == 4:
            self._start_stream(objs, reconfigure=True)
        else:
            logger.error('Unknown request type %d', request_type)

    def set_endpoints(self, value):
        '''Configure streaming endpoints.

        Called when iOS sets the SetupEndpoints Characteristic.
        '''
        objs = tlv.decode(base64ToBytes(value))
        session_id = objs[SETUP_TYPES['SESSION_ID']]

        # Extract address info
        address_tlv = objs[SETUP_TYPES['ADDRESS']]
        address_info_objs = tlv.decode(address_tlv)
        is_ipv6 = address_info_objs[SETUP_ADDR_INFO['ADDRESS_VER']][0]  #TODO
        address = address_info_objs[SETUP_ADDR_INFO['ADDRESS']].decode('utf8')
        target_video_port = struct.unpack(
            '<H', address_info_objs[SETUP_ADDR_INFO['VIDEO_RTP_PORT']])[0]
        target_audio_port = struct.unpack(
            '<H', address_info_objs[SETUP_ADDR_INFO['AUDIO_RTP_PORT']])[0]

        # Video SRTP Params
        video_srtp_tlv = objs[SETUP_TYPES['VIDEO_SRTP_PARAM']]
        video_info_objs = tlv.decode(video_srtp_tlv)
        video_crypto_suite = video_info_objs[SETUP_SRTP_PARAM['CRYPTO']][0]
        video_master_key = video_info_objs[SETUP_SRTP_PARAM['MASTER_KEY']]
        video_master_salt = video_info_objs[SETUP_SRTP_PARAM['MASTER_SALT']]

        # Audio SRTP Params
        audio_srtp_tlv = objs[SETUP_TYPES['AUDIO_SRTP_PARAM']]
        audio_info_objs = tlv.decode(audio_srtp_tlv)
        audio_crypto_suite = audio_info_objs[SETUP_SRTP_PARAM['CRYPTO']][0]
        audio_master_key = audio_info_objs[SETUP_SRTP_PARAM['MASTER_KEY']]
        audio_master_salt = audio_info_objs[SETUP_SRTP_PARAM['MASTER_SALT']]

        logger.debug('Received endpoint configuration:'
                     '\nsession_id: %s'
                     '\naddress: %s'
                     '\ntarget_video_port: %s'
                     '\ntarget_audio_port: %s'
                     '\nvideo_crypto_suite: %s'
                     '\nvideo_master_key: %s'
                     '\nvideo_master_salt: %s'
                     '\naudio_crypto_suite: %s'
                     '\naudio_master_key: %s'
                     '\naudio_master_salt: %s',
                     session_id, address, target_video_port, target_audio_port,
                     video_crypto_suite, video_master_key, video_master_salt,
                     audio_crypto_suite, audio_master_key, audio_master_salt)

        if self.support_srtp:
            video_srtp_tlv = tlv.encode(
                SETUP_SRTP_PARAM['CRYPTO'], SRTP_CRYPTO_SUITES['AES_CM_128_HMAC_SHA1_80'],
                SETUP_SRTP_PARAM['MASTER_KEY'], video_master_key,
                SETUP_SRTP_PARAM['MASTER_SALT'], video_master_salt)

            audio_srtp_tlv = tlv.encode(
                SETUP_SRTP_PARAM['CRYPTO'], SRTP_CRYPTO_SUITES['AES_CM_128_HMAC_SHA1_80'],
                SETUP_SRTP_PARAM['MASTER_KEY'], audio_master_key,
                SETUP_SRTP_PARAM['MASTER_SALT'], audio_master_salt)
        else:
            video_srtp_tlv = self.NO_SRTP
            audio_srtp_tlv = self.NO_SRTP

        video_ssrc = b'\x01'  #os.urandom(4)
        audio_ssrc = b'\x01'  #os.urandom(4)

        res_address_tlv = tlv.encode(
            SETUP_ADDR_INFO['ADDRESS_VER'], self.stream_address_isv6,
            SETUP_ADDR_INFO['ADDRESS'], self.stream_address.encode('utf-8'),
            SETUP_ADDR_INFO['VIDEO_RTP_PORT'], struct.pack('<H', target_video_port),
            SETUP_ADDR_INFO['AUDIO_RTP_PORT'], struct.pack('<H', target_audio_port))

        response_tlv = tlv.encode(
            SETUP_TYPES['SESSION_ID'], session_id,
            SETUP_TYPES['STATUS'], SETUP_STATUS['SUCCESS'],
            SETUP_TYPES['ADDRESS'], res_address_tlv,
            SETUP_TYPES['VIDEO_SRTP_PARAM'], video_srtp_tlv,
            SETUP_TYPES['AUDIO_SRTP_PARAM'], audio_srtp_tlv,
            SETUP_TYPES['VIDEO_SSRC'], video_ssrc,
            SETUP_TYPES['AUDIO_SSRC'], audio_ssrc)

        self.sessions[session_id] = {
            'address': address,
            'video_port': target_video_port,
            'video_srtp_key': video_master_key,
            'video_srtp_salt': video_master_salt,
            'video_ssrc': video_ssrc,
            'audio_port': target_audio_port,
            'audio_srtp_key': audio_master_key,
            'audio_srtp_salt': audio_master_salt,
            'audio_ssrc': audio_ssrc
        }

        endpoints = self.management_service.get_characteristic('SetupEndpoints')
        endpoints.set_value(toBase64Str(response_tlv))

    def get_snapshot(self, image_size):
        with open(os.path.join(RESOURCE_DIR, 'snapshot.jpg'), 'rb') as fp:
            return fp.read()


    def _run(self):
        import time
        time.sleep(3)
        self.streaming_status = STREAMING_STATUS["STREAMING"]
        self.management_service.get_characteristic("StreamingStatus").set_value(self._get_streaimg_status())
