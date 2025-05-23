# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import srgen_pb2 as srgen__pb2


class SrgenStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.NewJob = channel.unary_unary(
                '/srgen.Srgen/NewJob',
                request_serializer=srgen__pb2.JobRequest.SerializeToString,
                response_deserializer=srgen__pb2.JobReply.FromString,
                )
        self.QueryJobs = channel.unary_unary(
                '/srgen.Srgen/QueryJobs',
                request_serializer=srgen__pb2.JobStatusRequest.SerializeToString,
                response_deserializer=srgen__pb2.JobStatusReply.FromString,
                )
        self.Add = channel.unary_unary(
                '/srgen.Srgen/Add',
                request_serializer=srgen__pb2.AdditionRequest.SerializeToString,
                response_deserializer=srgen__pb2.AdditionResponse.FromString,
                )


class SrgenServicer(object):
    """Missing associated documentation comment in .proto file."""

    def NewJob(self, request, context):
        """new job, run img super-resolution
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


def add_SrgenServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'NewJob': grpc.unary_unary_rpc_method_handler(
                    servicer.NewJob,
                    request_deserializer=srgen__pb2.JobRequest.FromString,
                    response_serializer=srgen__pb2.JobReply.SerializeToString,
            ),
            'QueryJobs': grpc.unary_unary_rpc_method_handler(
                    servicer.QueryJobs,
                    request_deserializer=srgen__pb2.JobStatusRequest.FromString,
                    response_serializer=srgen__pb2.JobStatusReply.SerializeToString,
            ),
            'Add': grpc.unary_unary_rpc_method_handler(
                    servicer.Add,
                    request_deserializer=srgen__pb2.AdditionRequest.FromString,
                    response_serializer=srgen__pb2.AdditionResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'srgen.Srgen', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class Srgen(object):
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
        return grpc.experimental.unary_unary(request, target, '/srgen.Srgen/NewJob',
            srgen__pb2.JobRequest.SerializeToString,
            srgen__pb2.JobReply.FromString,
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
        return grpc.experimental.unary_unary(request, target, '/srgen.Srgen/QueryJobs',
            srgen__pb2.JobStatusRequest.SerializeToString,
            srgen__pb2.JobStatusReply.FromString,
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
        return grpc.experimental.unary_unary(request, target, '/srgen.Srgen/Add',
            srgen__pb2.AdditionRequest.SerializeToString,
            srgen__pb2.AdditionResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
