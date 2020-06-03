#!/usr/bin/env python3
"""
    Script to handle client connection as a server
"""
import threading
import json
import sys
import os
import math
import hashlib

from encryptlib.json_message import JsonMessage
from encryptlib.print_helper import PrintHelper
from encryptlib.SimonCTR import countermode_decrypt

BUFFER_SIZE = 32000
HEADER_SIZE = 9

class ClientThread(threading.Thread):
    def __init__(self,clientsocket, client_address, public_key, private_key):
        """
        Default constructor or class handling client socket thread
        """
        threading.Thread.__init__(self)
        self.clientd = clientsocket
        self.public_key = public_key
        self.private_key = private_key
        self.pprint = PrintHelper()


    def run(self):
        """
        Function to handle client socket thread execution
        """
        while True:
            data = self.clientd.recv(BUFFER_SIZE)
            bytes_recv = len(data)
            msg = data.decode()

            """
                Close connection.
            """
            if self.is_valid_request(msg):
                # 1. Process Response
                self.process_request()

                # 2. Build Response
                self.build_response()

                # 3. Send Response
                self.clientd.send(bytes(self.response, 'UTF-8'))
            else:
                self.clientd.close()
                break

            """
                Need to wait for File Header and Data now
            """
            data = self.clientd.recv(BUFFER_SIZE)
            msg = data.decode()

            if self.is_valid_file_header(data):
                print('Valid File Header')
            else:
                self.clientd.close()
                break
            break

    def is_valid_request(self, request):
        """
        Function to validate request
        """
        req_type = request[0]
        req_length = request[1:9]

        if req_type != '1':
            return False

        try:
            length = int(req_length)
        except ValueError:
            # sent us data that is NOT just digits 0-9
            return False

        # Attempt to get json object
        payload = request[9: length + 9]

        try:
            self.json_request = json.loads(payload)
        except json.JSONDecodeError:
            # invalid JSON object
            return False

        self.pprint.received('\nRequest >>>\n----------\n{0}\n----------'.format(request))
        return True

    def build_response(self):
        """
        Function to handle sending a response to the client
        """
        self.json_response = JsonMessage()
        self.create_sess_key()

        # Determine length of JSON payload
        length = len(self.json_response.__str__())
        length_str = '{:08d}'.format(length)

        # form entire request
        self.response = '{0}{1}{2}'.format('2', length_str, self.json_response.__str__())
        self.pprint.sent('\nResponse <<<\n----------\n{0}\n----------'.format(self.response))

    def process_request(self):
        """
        Function used to process the request get contents from payload
        """
        """
            Begin Processing request JSON object
        """
        self.decrypt_sess_key()
        self.decrypt_payload()
        is_valid_sign = self.verify_sign()

        if is_valid_sign:
            # continue processing
            is_valid_hash = self.verify_hash()

            if is_valid_sign:
                # Now need to start building response
                # hence return and call self.build_response()
                return
            else:
                #close connection
                pass
        else:
            # need to close connection
            pass

    def create_sess_key(self):
        """
        Function to create sess_key.key value
        """
        # 1. create a 256 bit session key
        key_int = int.from_bytes(get_random_bytes(32), byteorder='little')

        self.sess_key = {
            "key": key_int
        }

        key_str = str(key_int)

        sess_key = {
            "key": key_str
        }

        self.json_request.dhke_data["sess_key"] = sess_key

    def verify_hash(self):
        """
        Function to verify sess_key_hash
        """
        raw_sess_key = json.dumps(self.json_request["sess_key"])

        m = hashlib.sha3_512()
        m.update(bytes(raw_sess_key, 'utf-8'))
        byte_value = m.digest()
        hash_sess_str = str(int.from_bytes(byte_value, byteorder='little'))

        if hash_sess_str == self.json_request["payload"]["agreement_data"]["hash_sess_key"]:
            return True
        else:
            return False

    def verify_sign(self):
        """
        Function to verify signature of packet 1 from talker
        """
        signature_raw = self.json_request["payload"]["signature"]
        int_val = int(signature_raw)

        sign_val = pow(int_val, self.public_key.e, self.public_key.n)

        data_raw = json.dumps(self.json_request["payload"]["agreement_data"])
        m = hashlib.sha3_512()
        m.update(bytes(data_raw, 'utf-8'))

        hash_bytes = m.digest()
        hash_int = int.from_bytes(hash_bytes, byteorder='little')

        if sign_val == hash_int:
            return True
        else:
            return False

    def decrypt_payload(self):
        """
        Function used to decrypt payload of request
        """
        key = int(self.json_request["sess_key"]["key"])
        nonce = int(self.json_request["sess_key"]["ToD"])

        data_raw = self.json_request["payload"]
        data_int = int(data_raw)
        data_int_in_binary = bin(data_int)[2:]

        m1_c = countermode_decrypt(data_int_in_binary, nonce, key)
        m1_c_dec = int(m1_c, 2)
        m1_c_str = str(m1_c_dec)

        length = int(math.ceil(m1_c_dec.bit_length() / 8))

        payload_str = m1_c_dec.to_bytes(length, byteorder='little')
        # TODO: Something's this fails, idk why
        payload_str = payload_str.decode('utf-8')

        self.json_request["payload"] = json.loads(payload_str)

    def decrypt_sess_key(self):
        """
        Function used to decrypt the sess_key we received in request
        """
        data_raw = self.json_request["sess_key"]
        data_int = int(data_raw)

        sess_key_decrypted = pow(data_int, self.private_key.d, self.private_key.n)

        length = int(math.ceil(sess_key_decrypted.bit_length() / 8))

        sess_str = sess_key_decrypted.to_bytes(length, byteorder='little')
        sess_str = sess_str.decode('utf-8')

        self.json_request["sess_key"] = json.loads(sess_str)

    def is_valid_file_header(self, message):
        """
        Function to determine if File Header is valid
        """
        if len(message) < 9:
            return False

        header_type = message[0]
        length_str = message[1:9]

        if header_type != '3':
            return False

        try:
            length = int(length_str)
        except ValueError:
            return False

        # Attempt to get json object
        payload = message[9: length + 9]

        try:
            self.json_header = json.loads(payload)
        except json.JSONDecodeError:
            # invalid JSON object
            return False

        return True
