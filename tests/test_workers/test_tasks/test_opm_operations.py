# SPDX-License-Identifier: GPL-3.0-or-later
import os.path
import pytest
import textwrap

from unittest import mock

from iib.exceptions import IIBError, AddressAlreadyInUse
from iib.workers.config import get_worker_config
from iib.workers.tasks import opm_operations


@pytest.fixture()
def mock_config():
    with mock.patch('iib.workers.tasks.opm_operations.get_worker_config') as mc:
        mc.return_value = {
            'iib_grpc_start_port': 50051,
            'iib_grpc_init_wait_time': 1,
            'iib_grpc_max_port_tries': 3,
            'iib_grpc_max_tries': 3,
        }
        yield mc


def test_gen_port_for_grp():
    conf = get_worker_config()
    port_start = conf['iib_grpc_start_port']
    port_end = port_start + conf['iib_grpc_max_port_tries']
    port_range = set(range(port_start, port_end))

    with pytest.raises(
        IIBError, match=f'No free port has been found after {len(port_range)} attempts.'
    ):
        for port in opm_operations._gen_port_for_grpc():
            assert port in port_range


@mock.patch('iib.workers.tasks.opm_operations._gen_port_for_grpc')
@mock.patch('iib.workers.tasks.opm_operations._serve_cmd_at_port')
def test_opm_registry_serve(mock_scap, mock_gpfg):
    mock_scap.side_effect = [AddressAlreadyInUse(), AddressAlreadyInUse(), (50053, 456)]
    mock_gpfg.return_value = iter([50051, 50052, 50053])
    port, _ = opm_operations.opm_registry_serve(db_path='some_path.db')
    assert port == 50053
    assert mock_scap.call_count == 3


@mock.patch('iib.workers.tasks.opm_operations._serve_cmd_at_port')
def test_opm_registry_serve_no_ports(mock_scap, mock_config):
    mock_scap.side_effect = AddressAlreadyInUse()
    with pytest.raises(IIBError, match='No free port has been found after 3 attempts.'):
        opm_operations.opm_registry_serve(db_path='some_path.db')
    mock_scap.call_count = 3


@mock.patch('iib.workers.tasks.opm_operations._gen_port_for_grpc')
@mock.patch('iib.workers.tasks.opm_operations._serve_cmd_at_port')
def test_opm_serve(mock_scap, mock_gpfg):
    mock_scap.side_effect = [AddressAlreadyInUse(), AddressAlreadyInUse(), (50053, 456)]
    mock_gpfg.return_value = iter([50051, 50052, 50053])
    port, _ = opm_operations.opm_serve(catalog_dir='/some/dir')
    assert port == 50053
    assert mock_scap.call_count == 3


@mock.patch('iib.workers.tasks.opm_operations._serve_cmd_at_port')
def test_opm_serve_no_ports(mock_scap, mock_config):
    mock_scap.side_effect = AddressAlreadyInUse()
    with pytest.raises(IIBError, match='No free port has been found after 3 attempts.'):
        opm_operations.opm_serve(catalog_dir='/some/dir')
    assert mock_scap.call_count == 3


@pytest.mark.parametrize('is_fbc', (True, False))
@mock.patch('iib.workers.tasks.opm_operations.get_catalog_dir')
@mock.patch('iib.workers.tasks.build._get_index_database')
@mock.patch('iib.workers.tasks.opm_operations.is_image_fbc')
@mock.patch('iib.workers.tasks.opm_operations._gen_port_for_grpc')
@mock.patch('iib.workers.tasks.opm_operations._serve_cmd_at_port')
def test_opm_serve_from_index(
    mock_scap,
    mock_gpfg,
    mock_ifbc,
    mock_gid,
    mock_cd,
    tmpdir,
    is_fbc,
):
    my_mock = mock.MagicMock()
    mock_ifbc.return_value = is_fbc
    mock_gid.return_value = "some.db"
    mock_cd.return_value = "/some/path"
    my_mock.poll.return_value = None
    mock_scap.side_effect = [AddressAlreadyInUse(), AddressAlreadyInUse(), (50053, 456)]
    mock_gpfg.return_value = iter([50051, 50052, 50053])
    port, _ = opm_operations.opm_serve_from_index(
        base_dir=tmpdir, from_index='docker://test_pull_spec:latest'
    )
    assert port == 50053
    assert mock_scap.call_count == 3


@mock.patch('time.time')
@mock.patch('time.sleep')
@mock.patch('subprocess.Popen')
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_serve_cmd_at_port_not_initialize(
    mock_run_cmd, mock_popen, mock_sleep, mock_time, tmpdir, mock_config
):
    mock_run_cmd.side_effect = ['', '', '', '', ''] * 4
    mock_time.side_effect = list(range(1, 80))
    my_mock = mock.MagicMock()
    mock_popen.return_value = my_mock
    my_mock.poll.return_value = None

    cmd = ['opm', 'registry', 'serve', '-p', '50051', '-d', '/tmp/dummy.db', '-t', '/dev/null']
    with pytest.raises(IIBError, match='Index registry has not been initialized after 5 tries'):
        opm_operations._serve_cmd_at_port(" ".join(cmd), '/tmp', 50051, 5, 3)
    assert mock_run_cmd.call_count == 20


@mock.patch('time.time')
@mock.patch('time.sleep')
@mock.patch('subprocess.Popen')
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_serve_cmd_at_port_delayed_initialize(
    mock_run_cmd, mock_popen, mock_sleep, mock_time, tmpdir, mock_config
):
    mock_time.side_effect = [i * 0.5 for i in range(1, 80)]
    mock_run_cmd.side_effect = [
        '',
        '',
        '',
        '',
        '',
        '',
        'api.Registry.ListBundles',
    ]

    my_mock = mock.MagicMock()
    mock_popen.return_value = my_mock
    my_mock.poll.return_value = None

    cmd = ['opm', 'registry', 'serve', '-p', '50051', '-d', '/tmp/dummy.db', '-t', '/dev/null']
    opm_operations._serve_cmd_at_port(" ".join(cmd), '/tmp', 50051, 5, 3)
    assert mock_run_cmd.call_count == 7


@mock.patch('iib.workers.tasks.opm_operations.shutil.rmtree')
@mock.patch('iib.workers.tasks.opm_operations.generate_cache_locally')
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_migrate(
    mock_run_cmd,
    mock_gcl,
    moch_srmtree,
    tmpdir,
):
    index_db_file = os.path.join(tmpdir, 'database/index.db')

    opm_operations.opm_migrate(index_db_file, tmpdir)
    moch_srmtree.assert_not_called()

    fbc_dir = os.path.join(tmpdir, 'catalog')

    mock_run_cmd.assert_called_once_with(
        ['opm', 'migrate', index_db_file, fbc_dir],
        {'cwd': tmpdir},
        exc_msg='Failed to migrate index.db to file-based catalog',
    )

    mock_gcl.assert_called_once_with(tmpdir, fbc_dir, mock.ANY)


@pytest.mark.parametrize("dockerfile", (None, 'index.Dockerfile'))
@mock.patch('iib.workers.tasks.utils.run_cmd')
@mock.patch('iib.workers.tasks.opm_operations.insert_cache_into_dockerfile')
def test_opm_generate_dockerfile(mock_icid, mock_run_cmd, tmpdir, dockerfile):
    index_db_file = os.path.join(tmpdir, 'database/index.db')
    fbc_dir = os.path.join(tmpdir, 'catalogs')

    def create_dockerfile(*args, **kwargs):
        with open(os.path.join(tmpdir, 'catalogs.Dockerfile'), 'a'):
            pass

    mock_run_cmd.side_effect = create_dockerfile

    opm_operations.opm_generate_dockerfile(
        fbc_dir, tmpdir, index_db_file, "some:image", dockerfile_name=dockerfile
    )

    df_name = dockerfile if dockerfile else f"{os.path.basename(fbc_dir)}.Dockerfile"

    mock_run_cmd.assert_called_once_with(
        ['opm', 'generate', 'dockerfile', fbc_dir, '--binary-image', 'some:image'],
        {'cwd': tmpdir},
        exc_msg='Failed to generate Dockerfile for file-based catalog',
    )

    df_path = os.path.join(tmpdir, df_name)
    with open(df_path, 'r') as f:
        assert any(line.find('/var/lib/iib/_hidden/do.not.edit.db') != -1 for line in f.readlines())

    mock_icid.assert_called_once_with(df_path)


@pytest.mark.parametrize("set_index_db_file", (False, True))
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_generate_dockerfile_no_dockerfile(mock_run_cmd, tmpdir, set_index_db_file):
    index_db_file = os.path.join(tmpdir, 'database/index.db') if set_index_db_file else None
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    df_path = os.path.join(tmpdir, f"{os.path.basename(fbc_dir)}.Dockerfile")

    with pytest.raises(IIBError, match=f"Cannot find generated Dockerfile at {df_path}"):
        opm_operations.opm_generate_dockerfile(
            fbc_dir,
            tmpdir,
            index_db_file,
            "some:image",
        )

    mock_run_cmd.assert_called_once_with(
        ['opm', 'generate', 'dockerfile', fbc_dir, '--binary-image', 'some:image'],
        {'cwd': tmpdir},
        exc_msg='Failed to generate Dockerfile for file-based catalog',
    )


@pytest.mark.parametrize("set_index_db_file", (False, True))
@pytest.mark.parametrize("dockerfile", (None, 'index.Dockerfile'))
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_generate_dockerfile_exist(mock_run_cmd, tmpdir, dockerfile, set_index_db_file):
    index_db_file = os.path.join(tmpdir, 'database/index.db') if set_index_db_file else None
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    df_name = f"{os.path.basename(fbc_dir)}.Dockerfile" if not dockerfile else dockerfile
    df_path = os.path.join(tmpdir, df_name)

    # create Dockerfile for tests
    with open(df_path, 'a'):
        pass

    opm_operations.opm_generate_dockerfile(
        fbc_dir, tmpdir, index_db_file, "some:image", dockerfile_name=dockerfile
    )

    mock_run_cmd.assert_not_called()


@pytest.mark.parametrize('from_index', (None, 'some_index:latest'))
@pytest.mark.parametrize('bundles', (['bundle:1.2', 'bundle:1.3'], []))
@pytest.mark.parametrize('overwrite_csv', (True, False))
@pytest.mark.parametrize('container_tool', (None, 'podwoman'))
@mock.patch('iib.workers.tasks.utils.set_registry_token')
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_registry_add(
    mock_run_cmd, mock_srt, from_index, bundles, overwrite_csv, container_tool
):
    opm_operations._opm_registry_add(
        base_dir='/tmp/somedir',
        index_db='/tmp/somedir/some.db',
        bundles=bundles,
        overwrite_csv=overwrite_csv,
        container_tool=container_tool,
    )

    mock_run_cmd.assert_called_once()
    opm_args = mock_run_cmd.call_args[0][0]
    assert opm_args[:3] == ['opm', 'registry', 'add']
    if bundles:
        assert ','.join(bundles) in opm_args
    else:
        assert '""' in opm_args
    if overwrite_csv:
        assert '--overwrite-latest' in opm_args
    else:
        assert '--overwrite-latest' not in opm_args
    if container_tool:
        assert '--container-tool' in opm_args
        assert container_tool in opm_args
    else:
        assert '--container-tool' not in opm_args
    assert "--enable-alpha" in opm_args


@pytest.mark.parametrize('is_fbc', (True, False))
@pytest.mark.parametrize('from_index', (None, 'some_index:latest'))
@pytest.mark.parametrize('bundles', (['bundle:1.2', 'bundle:1.3'], []))
@pytest.mark.parametrize('overwrite_csv', (True, False))
@pytest.mark.parametrize('container_tool', (None, 'podwoman'))
@pytest.mark.parametrize('graph_update_mode', (None, 'semver-skippatch'))
@mock.patch('iib.workers.tasks.opm_operations.opm_generate_dockerfile')
@mock.patch('iib.workers.tasks.opm_operations.opm_migrate')
@mock.patch('iib.workers.tasks.opm_operations._opm_registry_add')
@mock.patch('iib.workers.tasks.build._get_index_database')
@mock.patch('iib.workers.tasks.opm_operations.get_hidden_index_database')
@mock.patch('iib.workers.tasks.opm_operations.is_image_fbc')
def test_opm_registry_add_fbc(
    mock_iifbc,
    mock_ghid,
    mock_gid,
    mock_ora,
    mock_om,
    mock_ogd,
    from_index,
    bundles,
    overwrite_csv,
    container_tool,
    graph_update_mode,
    is_fbc,
    tmpdir,
):
    index_db_file = os.path.join(tmpdir, 'database/index.db')
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    cache_dir = os.path.join(tmpdir, 'cache')
    mock_ghid.return_value = index_db_file
    mock_gid.return_value = index_db_file
    mock_om.return_value = (fbc_dir, cache_dir)
    mock_iifbc.return_value = is_fbc

    opm_operations.opm_registry_add_fbc(
        base_dir=tmpdir,
        bundles=bundles,
        binary_image="some:image",
        from_index=from_index,
        graph_update_mode=graph_update_mode,
        overwrite_csv=overwrite_csv,
        container_tool=container_tool,
    )

    mock_ora.assert_called_once_with(
        base_dir=tmpdir,
        index_db=index_db_file,
        bundles=bundles,
        overwrite_csv=overwrite_csv,
        container_tool=container_tool,
        graph_update_mode=graph_update_mode,
    )

    mock_om.assert_called_once_with(index_db=index_db_file, base_dir=tmpdir)
    mock_ogd.assert_called_once_with(
        fbc_dir=fbc_dir,
        base_dir=tmpdir,
        index_db=index_db_file,
        binary_image="some:image",
        dockerfile_name='index.Dockerfile',
    )


@pytest.mark.parametrize('operators', (['abc-operator', 'xyz-operator'], []))
@mock.patch('iib.workers.tasks.opm_operations.opm_generate_dockerfile')
@mock.patch('iib.workers.tasks.opm_operations.opm_migrate')
@mock.patch('iib.workers.tasks.opm_operations._opm_registry_rm')
@mock.patch('iib.workers.tasks.opm_operations.get_hidden_index_database')
@mock.patch('iib.workers.tasks.utils.set_registry_token')
def test_opm_registry_rm_fbc(
    mock_srt,
    mock_ghid,
    mock_orr,
    mock_om,
    mock_ogd,
    tmpdir,
    operators,
):
    from_index = 'some_index:latest'
    index_db_file = os.path.join(tmpdir, 'database/index.db')
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    mock_ghid.return_value = index_db_file
    mock_om.return_value = (fbc_dir, None)

    opm_operations.opm_registry_rm_fbc(
        tmpdir, from_index, operators, 'some:image', overwrite_from_index_token='some_token'
    )

    mock_orr.assert_called_once_with(
        index_db_file,
        operators,
        tmpdir,
    )

    mock_srt.assert_called_once_with('some_token', 'some_index:latest', append=True)
    mock_om.assert_called_once_with(index_db=index_db_file, base_dir=tmpdir, generate_cache=True)
    mock_ogd.assert_called_once_with(
        fbc_dir=fbc_dir,
        base_dir=tmpdir,
        index_db=index_db_file,
        binary_image='some:image',
        dockerfile_name='index.Dockerfile',
    )


@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_registry_rm(mock_run_cmd):
    packages = ['abc-operator', 'xyz-operator']
    opm_operations._opm_registry_rm(
        '/tmp/somedir/some.db',
        packages,
        '/tmp/somedir',
    )

    mock_run_cmd.assert_called_once()
    opm_args = mock_run_cmd.call_args[0][0]
    assert opm_args[:3] == ['opm', 'registry', 'rm']
    assert ','.join(packages) in opm_args


@pytest.mark.parametrize(
    'from_index, is_fbc', [('some-fbc-index:latest', True), ('some-sqlite-index:latest', False)]
)
@mock.patch('iib.workers.tasks.opm_operations.opm_generate_dockerfile')
@mock.patch('iib.workers.tasks.opm_operations.opm_migrate')
@mock.patch('iib.workers.tasks.opm_operations._opm_registry_rm')
@mock.patch('iib.workers.tasks.opm_operations.get_hidden_index_database')
@mock.patch('iib.workers.tasks.build._get_index_database')
@mock.patch('iib.workers.tasks.opm_operations.is_image_fbc')
@mock.patch('iib.workers.tasks.opm_operations.set_request_state')
def test_opm_create_empty_fbc(
    mock_srs, mock_iif, mock_gid, mock_ghid, mock_orr, mock_om, mock_ogd, tmpdir, from_index, is_fbc
):

    operators = ['abc-operator', 'xyz-operator']
    mock_iif.return_value = is_fbc
    hidden_index_db_file = os.path.join(tmpdir, 'hidden/index.db')
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    cache_dir = os.path.join(tmpdir, 'cache')
    mock_ghid.return_value = hidden_index_db_file
    mock_om.return_value = (fbc_dir, cache_dir)

    index_db_file = os.path.join(tmpdir, 'database/index.db')
    mock_gid.return_value = index_db_file

    opm_operations.opm_create_empty_fbc(3, tmpdir, from_index, from_index, 'some:image', operators)

    if is_fbc:
        mock_orr.assert_called_once_with(
            index_db_path=hidden_index_db_file, operators=operators, base_dir=tmpdir
        )
        mock_ghid.assert_called_once()
    else:
        mock_gid.assert_called_once()
        mock_orr.assert_called_once_with(
            index_db_path=index_db_file, operators=operators, base_dir=tmpdir
        )


@pytest.mark.parametrize("from_index", (None, "image:latest"))
@pytest.mark.parametrize("db_exist", (True, False))
@mock.patch('iib.workers.tasks.opm_operations.is_image_fbc')
@mock.patch('iib.workers.tasks.opm_operations.get_hidden_index_database')
def test_get_or_create_temp_index_db_file(mock_ghid, mock_iifbc, db_exist, from_index, tmpdir):
    def create_index_db(*args, **kwargs):
        db_file = os.path.join(tmpdir, get_worker_config()['temp_index_db_path'])
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        with open(db_file, 'w'):
            pass
        return db_file

    mock_ghid.side_effect = create_index_db
    mock_iifbc.return_value = True

    if db_exist:
        create_index_db()

    index_db_file = opm_operations._get_or_create_temp_index_db_file(
        base_dir=tmpdir, from_index=from_index
    )
    assert os.path.isfile(index_db_file)


@pytest.mark.parametrize('bundles', (['bundle:1.2', 'bundle:1.3'], []))
@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_opm_registry_deprecatetruncate(mock_run_cmd, bundles):
    index_db_file = '/tmp/test_file.db'
    cmd = [
        'opm',
        'registry',
        'deprecatetruncate',
        '--database',
        index_db_file,
        '--bundle-images',
        ','.join(bundles),
        '--allow-package-removal',
    ]

    opm_operations.opm_registry_deprecatetruncate(
        base_dir='/tmp',
        index_db=index_db_file,
        bundles=bundles,
    )

    mock_run_cmd.assert_called_once_with(
        cmd, {'cwd': '/tmp'}, exc_msg=f'Failed to deprecate the bundles on {index_db_file}'
    )


@pytest.mark.parametrize('from_index', (None, 'some_index:latest'))
@pytest.mark.parametrize('bundles', (['bundle:1.2', 'bundle:1.3'], []))
@mock.patch('iib.workers.tasks.opm_operations.opm_generate_dockerfile')
@mock.patch('iib.workers.tasks.opm_operations.opm_migrate')
@mock.patch('iib.workers.tasks.opm_operations.opm_registry_deprecatetruncate')
@mock.patch('iib.workers.tasks.opm_operations._get_or_create_temp_index_db_file')
def test_deprecate_bundles_fbc(
    mock_gtidf,
    mock_ord,
    mock_om,
    mock_ogd,
    from_index,
    bundles,
    tmpdir,
):
    index_db_file = os.path.join(tmpdir, 'database/index.db')
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    cache_dir = os.path.join(tmpdir, 'cache')
    mock_gtidf.return_value = index_db_file
    mock_om.return_value = (fbc_dir, cache_dir)

    opm_operations.deprecate_bundles_fbc(
        bundles=bundles,
        base_dir=tmpdir,
        binary_image="some:image",
        from_index=from_index,
    )

    mock_ord.assert_called_once_with(base_dir=tmpdir, index_db=index_db_file, bundles=bundles)

    mock_om.assert_called_once_with(index_db_file, tmpdir)
    mock_ogd.assert_called_once_with(
        fbc_dir=fbc_dir,
        base_dir=tmpdir,
        index_db=index_db_file,
        binary_image="some:image",
        dockerfile_name='index.Dockerfile',
    )


@mock.patch('iib.workers.tasks.utils.run_cmd')
@mock.patch('iib.workers.tasks.opm_operations.os.path.isdir', return_value=True)
def test_generate_cache_locally(mock_isdir, mock_cmd, tmpdir):
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    local_cache_path = os.path.join(tmpdir, 'cache')
    cmd = [
        'opm',
        'serve',
        os.path.abspath(fbc_dir),
        f'--cache-dir={local_cache_path}',
        '--cache-only',
        '--termination-log',
        '/dev/null',
    ]

    opm_operations.generate_cache_locally(tmpdir, fbc_dir, local_cache_path)

    mock_cmd.assert_called_once_with(
        cmd, {'cwd': tmpdir}, exc_msg='Failed to generate cache for file-based catalog'
    )


@mock.patch('iib.workers.tasks.utils.run_cmd')
def test_generate_cache_locally_failed(mock_cmd, tmpdir):
    fbc_dir = os.path.join(tmpdir, 'catalogs')
    local_cache_path = os.path.join(tmpdir, 'cache')
    cmd = [
        'opm',
        'serve',
        os.path.abspath(fbc_dir),
        f'--cache-dir={local_cache_path}',
        '--cache-only',
        '--termination-log',
        '/dev/null',
    ]

    with pytest.raises(IIBError, match='Cannot find generated cache at .+'):
        opm_operations.generate_cache_locally(tmpdir, fbc_dir, local_cache_path)
        mock_cmd.assert_called_once_with(
            cmd, {'cwd': tmpdir}, exc_msg='Failed to generate cache for file-based catalog'
        )


def test_insert_cache_into_dockerfile(tmpdir):
    local_cache_dir = tmpdir.mkdir('cache')
    generated_dockerfile = local_cache_dir.join('catalog.Dockerfile')

    dockerfile_template = textwrap.dedent(
        """\
        ADD /configs
        RUN something-else
        {run_command}
        COPY . .
        """
    )

    generated_dockerfile.write(
        dockerfile_template.format(
            run_command=(
                'RUN ["/bin/opm", "serve", "/configs", "--cache-dir=/tmp/cache", "--cache-only"]'
            )
        )
    )

    opm_operations.insert_cache_into_dockerfile(generated_dockerfile)

    assert generated_dockerfile.read_text('utf-8') == dockerfile_template.format(
        run_command='COPY --chown=1001:0 cache /tmp/cache'
    )


def test_insert_cache_into_dockerfile_no_matching_line(tmpdir):
    local_cache_dir = tmpdir.mkdir('cache')
    generated_dockerfile = local_cache_dir.join('catalog.Dockerfile')

    dockerfile_template = textwrap.dedent(
        """\
        ADD /configs
        RUN something-else
        COPY . .
        """
    )

    generated_dockerfile.write(dockerfile_template)
    with pytest.raises(IIBError, match='Dockerfile edit to insert locally built cache failed.'):
        opm_operations.insert_cache_into_dockerfile(generated_dockerfile)


def test_verify_cache_insertion_edit_dockerfile():
    input_list = ['ADD /configs', 'COPY . .' 'COPY --chown=1001:0 cache /tmp/cache']
    opm_operations.verify_cache_insertion_edit_dockerfile(input_list)


def test_verify_cache_insertion_edit_dockerfile_failed():
    input_list = ['ADD /configs', 'COPY . .' 'RUN something']
    with pytest.raises(IIBError, match='Dockerfile edit to insert locally built cache failed.'):
        opm_operations.verify_cache_insertion_edit_dockerfile(input_list)


@pytest.mark.parametrize(
    'is_operator_exists, index_db_path', [(True, "index_path"), (False, "index_path")]
)
@mock.patch('iib.workers.tasks.opm_operations.opm_generate_dockerfile')
@mock.patch('iib.workers.tasks.opm_operations.generate_cache_locally')
@mock.patch('iib.workers.tasks.opm_operations.shutil.rmtree')
@mock.patch('iib.workers.tasks.opm_operations.shutil.copytree')
@mock.patch('iib.workers.tasks.opm_operations.os.listdir')
@mock.patch('iib.workers.tasks.opm_operations.opm_migrate')
@mock.patch('iib.workers.tasks.opm_operations._opm_registry_rm')
@mock.patch('iib.workers.tasks.opm_operations.get_catalog_dir')
@mock.patch('iib.workers.tasks.opm_operations.verify_operator_exists')
@mock.patch('iib.workers.tasks.opm_operations.extract_fbc_fragment')
@mock.patch('iib.workers.tasks.opm_operations.set_request_state')
def test_opm_registry_add_fbc_fragment(
    mock_srs,
    mock_eff,
    mock_voe,
    mock_gcr,
    mock_orr,
    mock_om,
    mock_ldr,
    mock_cpt,
    mock_rmt,
    mock_gcc,
    mock_ogd,
    is_operator_exists,
    index_db_path,
    tmpdir,
):
    from_index = "example.com/test/index"
    binary_image = "example.com/ose/binary"
    fbc_fragment = "example.com/test/fragment"
    fbc_fragment_operator = "test-operator"
    mock_eff.return_value = (os.path.join(tmpdir, "fbc_fragment"), fbc_fragment_operator)
    mock_voe.return_value = is_operator_exists, index_db_path
    mock_gcr.return_value = os.path.join(tmpdir, "configs")
    mock_om.return_value = os.path.join(tmpdir, "catalog"), None
    mock_ldr.return_value = [
        "package1",
    ]
    opm_operations.opm_registry_add_fbc_fragment(
        10, tmpdir, from_index, binary_image, fbc_fragment, None
    )
    mock_eff.assert_called_with(temp_dir=tmpdir, fbc_fragment=fbc_fragment)
    mock_voe.assert_called_with(
        from_index=from_index,
        base_dir=tmpdir,
        operator_package=fbc_fragment_operator,
        overwrite_from_index_token=None,
    )
    mock_gcr.assert_called_with(from_index=from_index, base_dir=tmpdir)
    if is_operator_exists:
        mock_orr.assert_called_with(
            index_db_path=index_db_path, operators=[fbc_fragment_operator], base_dir=tmpdir
        )
        mock_om.assert_called_with(index_db=index_db_path, base_dir=tmpdir, generate_cache=False)
        mock_cpt.assert_has_calls(
            [
                mock.call(
                    os.path.join(tmpdir, "catalog", mock_ldr.return_value[0]),
                    os.path.join(tmpdir, "configs", mock_ldr.return_value[0]),
                    dirs_exist_ok=True,
                ),
            ]
        )
        assert mock_cpt.call_count == 2
    else:
        assert mock_cpt.call_count == 1
        assert mock_orr.call_count == 0
    mock_srs.call_count == 2
    mock_cpt.assert_has_calls(
        [
            mock.call(
                os.path.join(tmpdir, "fbc_fragment", fbc_fragment_operator),
                os.path.join(tmpdir, "configs", fbc_fragment_operator),
            )
        ]
    )
    mock_gcc.assert_called_once()
    mock_ogd.assert_called_once()


@pytest.mark.parametrize(
    'bundles_in_db, opr_exists',
    [
        (
            '{"packageName": "test-operator", "version": "v1.0", "bundlePath":"bundle1"\n}'
            '\n{\n"packageName": "package2", "version": "v2.0", "bundlePath":"bundle2"}',
            True,
        ),
        (
            '{"packageName": "package1", "version": "v1.0", "bundlePath":"bundle1"\n}'
            '\n{\n"packageName": "package2", "version": "v2.0", "bundlePath":"bundle2"}',
            False,
        ),
    ],
)
@mock.patch('iib.workers.tasks.utils.terminate_process')
@mock.patch('iib.workers.tasks.utils.run_cmd')
@mock.patch('iib.workers.tasks.opm_operations.opm_registry_serve')
@mock.patch('iib.workers.tasks.build._copy_files_from_image')
@mock.patch('iib.workers.tasks.utils.set_registry_token')
def test_verify_operator_exists(
    mock_srt, mock_cffi, mock_ors, mock_rc, mock_tp, bundles_in_db, opr_exists, tmpdir
):
    from_index = "example.com/test/index"
    mock_ors.return_value = 500, mock.MagicMock()
    mock_rc.return_value = bundles_in_db
    index_db_path = os.path.join(tmpdir, get_worker_config()['temp_index_db_path'])
    package_exists, index_db_path = opm_operations.verify_operator_exists(
        from_index, tmpdir, 'test-operator', None
    )
    mock_ors.assert_has_calls([mock.call(db_path=index_db_path)])
    assert package_exists == opr_exists
