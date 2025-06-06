# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import texcreator_pb2 as texcreator__pb2


class TexcreatorStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.NewJob = channel.unary_unary(
                '/texcreator.Texcreator/NewJob',
                request_serializer=texcreator__pb2.JobRequest.SerializeToString,
                response_deserializer=texcreator__pb2.JobReply.FromString,
                )
        self.QueryJobs = channel.unary_unary(
                '/texcreator.Texcreator/QueryJobs',
                request_serializer=texcreator__pb2.JobStatusRequest.SerializeToString,
                response_deserializer=texcreator__pb2.JobStatusReply.FromString,
                )
        self.Add = channel.unary_unary(
                '/texcreator.Texcreator/Add',
                request_serializer=texcreator__pb2.AdditionRequest.SerializeToString,
                response_deserializer=texcreator__pb2.AdditionResponse.FromString,
                )


class TexcreatorServicer(object):
    """Missing associated documentation comment in .proto file."""

    def NewJob(self, request, context):
        """new job, run obj texture creator
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def QueryJobs(self, request, context):
        """query job status once 
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def Add(self, request, context):
        """Add func for debug
        """
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_TexcreatorServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'NewJob': grpc.unary_unary_rpc_method_handler(
                    servicer.NewJob,
                    request_deserializer=texcreator__pb2.JobRequest.FromString,
                    response_serializer=texcreator__pb2.JobReply.SerializeToString,
            ),
            'QueryJobs': grpc.unary_unary_rpc_method_handler(
                    servicer.QueryJobs,
                    request_deserializer=texcreator__pb2.JobStatusRequest.FromString,
                    response_serializer=texcreator__pb2.JobStatusReply.SerializeToString,
            ),
            'Add': grpc.unary_unary_rpc_method_handler(
                    servicer.Add,
                    request_deserializer=texcreator__pb2.AdditionRequest.FromString,
                    response_serializer=texcreator__pb2.AdditionResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'texcreator.Texcreator', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class Texcreator(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def NewJob(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/texcreator.Texcreator/NewJob',
            texcreator__pb2.JobRequest.SerializeToString,
            texcreator__pb2.JobReply.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def QueryJobs(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/texcreator.Texcreator/QueryJobs',
            texcreator__pb2.JobStatusRequest.SerializeToString,
            texcreator__pb2.JobStatusReply.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def Add(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/texcreator.Texcreator/Add',
            texcreator__pb2.AdditionRequest.SerializeToString,
            texcreator__pb2.AdditionResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
