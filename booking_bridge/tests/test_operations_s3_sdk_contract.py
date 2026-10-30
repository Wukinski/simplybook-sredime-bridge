"""Optional real pinned SDK contract checks; no sockets or cloud credentials."""
import hashlib
import io
import json

import pytest

from booking_bridge.deploy.offhost_backup import S3Transport


def test_real_pinned_sdk_accepts_conditional_put_and_all_used_operations(tmp_path):
    boto3 = pytest.importorskip('boto3', reason='Optional operations SDK is installed separately')
    botocore = pytest.importorskip('botocore')
    from botocore.response import StreamingBody
    from botocore.stub import Stubber
    assert boto3.__version__ == botocore.__version__ == '1.43.119'
    credentials = tmp_path / 'synthetic-credentials.json'
    credentials.write_text(json.dumps({'access_key_id': 'SYNTHETIC_ACCESS_KEY',
                                      'secret_access_key': 'SYNTHETIC_SECRET_KEY'}))
    credentials.chmod(0o600)
    config = {'source_database': str(tmp_path / 'unused.sqlite'), 'key_file': str(tmp_path / 'unused.key'),
        'spool_directory': str(tmp_path / 'unused-spool'), 'credentials_file': str(credentials),
        'endpoint_url': 'https://s3.synthetic.invalid', 'region': 'us-east-1',
        'bucket': 'synthetic-backup-bucket', 'prefix': 'bridge/backups/',
        'destination_independent_of_source': True, 'retention_days': 30, 'keep_last': 48,
        'delete_expired': False, 'budget_files': [], 'budget_floors': []}
    transport = S3Transport(config)
    client = transport.client
    assert client.meta.config.signature_version == 's3v4'
    assert client.meta.config.request_checksum_calculation == 'when_required'
    assert client.meta.config.response_checksum_validation == 'when_required'
    assert client.meta.config.retries['total_max_attempts'] == 2
    body = b'SYNTHETIC_ENCRYPTED_OBJECT'
    digest, key = hashlib.sha256(body).hexdigest(), 'bridge/backups/synthetic.enc'
    with Stubber(client) as stubber:
        stubber.add_response('put_object', {}, {'Bucket': config['bucket'], 'Key': key,
            'Body': body, 'ContentType': 'application/octet-stream',
            'Metadata': {'ciphertext-sha256': digest}, 'IfNoneMatch': '*'})
        stubber.add_response('get_object', {'ContentLength': len(body),
            'Body': StreamingBody(io.BytesIO(body), len(body))}, {'Bucket': config['bucket'], 'Key': key})
        stubber.add_response('list_objects_v2', {'Contents': [{'Key': key}], 'IsTruncated': False},
            {'Bucket': config['bucket'], 'Prefix': config['prefix'], 'MaxKeys': 1000})
        stubber.add_response('delete_object', {}, {'Bucket': config['bucket'], 'Key': key})
        transport.upload(key, body, digest)
        assert transport.download(key) == body
        assert transport.objects() == [key]
        transport.delete(key)
        stubber.assert_no_pending_responses()
