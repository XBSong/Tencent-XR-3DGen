# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: service.proto
# Protobuf Python Version: 4.25.0
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\rservice.proto\x12\x07\x65xample\"2\n\x0eRunFuncRequest\x12\x0f\n\x07in_mesh\x18\x01 \x01(\t\x12\x0f\n\x07out_glb\x18\x02 \x01(\t\"1\n\x0fRunFuncResponse\x12\x0e\n\x06job_id\x18\x01 \x01(\t\x12\x0e\n\x06result\x18\x02 \x01(\t\"\x16\n\x14QueryRunStateRequest\"x\n\x15QueryRunStateResponse\x12\x34\n\x04jobs\x18\x01 \x03(\x0b\x32&.example.QueryRunStateResponse.JobData\x1a)\n\x07JobData\x12\x0e\n\x06job_id\x18\x01 \x01(\t\x12\x0e\n\x06status\x18\x02 \x01(\t\"\"\n\x10\x43\x61ncelJobRequest\x12\x0e\n\x06job_id\x18\x01 \x01(\t\"#\n\x11\x43\x61ncelJobResponse\x12\x0e\n\x06status\x18\x01 \x01(\t2\xe5\x01\n\x0bMeshService\x12>\n\x07RunFunc\x12\x17.example.RunFuncRequest\x1a\x18.example.RunFuncResponse\"\x00\x12P\n\rQueryRunState\x12\x1d.example.QueryRunStateRequest\x1a\x1e.example.QueryRunStateResponse\"\x00\x12\x44\n\tCancelJob\x12\x19.example.CancelJobRequest\x1a\x1a.example.CancelJobResponse\"\x00\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'service_pb2', _globals)
if _descriptor._USE_C_DESCRIPTORS == False:
  DESCRIPTOR._options = None
  _globals['_RUNFUNCREQUEST']._serialized_start=26
  _globals['_RUNFUNCREQUEST']._serialized_end=76
  _globals['_RUNFUNCRESPONSE']._serialized_start=78
  _globals['_RUNFUNCRESPONSE']._serialized_end=127
  _globals['_QUERYRUNSTATEREQUEST']._serialized_start=129
  _globals['_QUERYRUNSTATEREQUEST']._serialized_end=151
  _globals['_QUERYRUNSTATERESPONSE']._serialized_start=153
  _globals['_QUERYRUNSTATERESPONSE']._serialized_end=273
  _globals['_QUERYRUNSTATERESPONSE_JOBDATA']._serialized_start=232
  _globals['_QUERYRUNSTATERESPONSE_JOBDATA']._serialized_end=273
  _globals['_CANCELJOBREQUEST']._serialized_start=275
  _globals['_CANCELJOBREQUEST']._serialized_end=309
  _globals['_CANCELJOBRESPONSE']._serialized_start=311
  _globals['_CANCELJOBRESPONSE']._serialized_end=346
  _globals['_MESHSERVICE']._serialized_start=349
  _globals['_MESHSERVICE']._serialized_end=578
# @@protoc_insertion_point(module_scope)
