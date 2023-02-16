from dateutil.parser import parse
import glob
from http.cookiejar import MozillaCookieJar
import uuid
from sentinelsat import SentinelAPI

from utils.prep_utils import *

from utils.s1am.raw2ard import Raw2Ard


root = setup_logging()

def find_s1_uuid(s1_filename):
    """
    Returns S2 uuid required for download via sentinelsat, based upon an input S2 file/scene name. 
    I.e. S2A_MSIL1C_20180820T223011_N0206_R072_T60KWE_20180821T013410
    Assumes esa hub creds stored as env variables.
    
    :param s2_file_name: Sentinel-2 scene name
    :return s2_uuid: download id
    """
    copernicus_username = os.getenv("COPERNICUS_USERNAME")
    copernicus_pwd = os.getenv("COPERNICUS_PWD")
    logging.debug(f"ESA username: {copernicus_username}")
    esa_api = SentinelAPI(copernicus_username, copernicus_pwd)

    if s1_filename[-5:] == '.SAFE':
        res = esa_api.query(filename=s1_filename)
        res = esa_api.to_geodataframe(res)

        return res.uuid.values[0]
        
def download_extract_s1_esa(scene_uuid, down_dir, original_scene_dir):
    """
    Download a single S2 scene from ESA via sentinelsat 
    based upon uuid. 
    Assumes esa hub creds stored as env variables.
    
    :param scene_uuid: S2 download uuid from sentinelsat query
    :param down_dir: directory in which to create a downloaded product dir
    :param original_scene_dir: 
    :return: 
    """
    # if unzipped .SAFE file doesn't exist then we must do something
    if not os.path.exists(original_scene_dir):

        # if downloaded .zip file doesn't exist then download it
        if not os.path.exists(original_scene_dir.replace('.SAFE/', '.zip')):
            logging.info('Downloading ESA scene zip: {}'.format(os.path.basename(original_scene_dir)))

            copernicus_username = os.getenv("COPERNICUS_USERNAME")
            copernicus_pwd = os.getenv("COPERNICUS_PWD")
            logging.debug(f"ESA username: {copernicus_username}")

            try:
                esa_api = SentinelAPI(copernicus_username, copernicus_pwd)
                esa_api.download(scene_uuid, down_dir, checksum=True)
            except Exception as e:
                raise DownloadError(f"Error downloading {scene_uuid} from ESA hub: {e}")

    else:
        logging.warning('ESA scene already extracted: {}'.format(original_scene_dir))

    # remove zipped scene but onliy if unzipped 
    if os.path.exists(original_scene_dir) & os.path.exists(original_scene_dir.replace('.SAFE/', '.zip')):
        logging.info('Deleting ESA scene zip: {}'.format(original_scene_dir.replace('.SAFE/', '.zip')))
        os.remove(original_scene_dir.replace('.SAFE/', '.zip'))


def band_name_s1(prod_path):
    """
    Determine polarisation of individual product from product name
    from path to specific product file
    """

    prod_name = str(prod_path.split('/')[-1])

    if '-vh-' in str(prod_name):
        return 'vh'
    if '-vv-' in str(prod_name):
        return 'vv'
    if 'LayoverShadow_MASK' in str(prod_name):
        return 'layovershadow_mask'

    logging.error(f"could not find band name for {prod_path}")

    return 'unknown layer'


def conv_s1scene_cogs(noncog_scene_dir, cog_scene_dir, scene_name, overwrite=False):
    """
    Convert S1 scene products to cogs [+ validate].
    """

    if not os.path.exists(noncog_scene_dir):
        logging.warning('Cannot find non-cog scene directory: {}'.format(noncog_scene_dir))

    # create cog scene directory - replace with one lined os.makedirs(exists_ok=True)
    if not os.path.exists(cog_scene_dir):
        logging.warning('Creating scene cog directory: {}'.format(cog_scene_dir))
        os.mkdir(cog_scene_dir)

    des_prods = ["Gamma0_VV_db",
                 "Gamma0_VH_db",
                 "LayoverShadow_MASK_VH"]  # to ammend once outputs finalised - TO DO*****

    # find all individual prods to convert to cog (ignore true colour images (TCI))
    prod_paths = glob.glob(noncog_scene_dir + '*TF_TC*/*.tif')  # - TO DO*****
    prod_paths = [x for x in prod_paths if os.path.basename(x)[:-4] in des_prods]

    # iterate over prods to create parellel processing list
    for prod in prod_paths:
        out_filename = os.path.join(cog_scene_dir, scene_name + '_' + os.path.basename(prod)[:-4] + '.tif')  # - TO DO*****
        logging.info(f"converting {prod} to cog at {out_filename}")
        # ensure input file exists
        to_cog(prod, out_filename, nodata=-9999)


def copy_s1_metadata(out_s1_prod, cog_scene_dir, scene_name):
    """
    Parse through S2 metadtaa .xml for either l1c or l2a S2 scenes.
    """

    if os.path.exists(out_s1_prod):

        meta_base = os.path.basename(out_s1_prod)
        n_meta = os.path.join(cog_scene_dir + '/' + scene_name + '_' + meta_base)
        logging.info("Copying original metadata file to cog dir: {}".format(n_meta))
        if not os.path.exists(n_meta):
            shutil.copyfile(out_s1_prod, n_meta)
        else:
            logging.info("Original metadata file already copied to cog_dir: {}".format(n_meta))
    else:
        logging.warning("Cannot find orignial metadata file: {}".format(out_s1_prod))


def yaml_prep_s1(scene_dir):
    """
    Prepare individual S1 scene directory containing S1 products
    note: doesn't inc. additional ancillary products such as incidence
    angle or layover/foreshortening masks
    """
    scene_name = scene_dir.split('/')[-2]
    
    # Get rid of the last part of the path
    scene_dir = scene_dir.split('/')[0:-1]
    scene_dir = '/'.join(scene_dir)
    logging.info("Scene path {}".format(scene_dir)) # /tmp/data/intermediate/S1A_IW_GRDH_1SDV_20230118T174108_tmp

    prod_paths = []
    for root, dirs, files in os.walk(scene_dir):
        for file in files:
            if file.endswith('.tiff'):
                prod_paths.append(os.path.join(root, file))
    
    logging.debug(f"Found {len(prod_paths)} products")

    t0 = parse(str(datetime.strptime(scene_name.split("_")[-2], '%Y%m%dT%H%M%S')))

    # get polorisation from each image product (S1 band)
    # should be replaced with a more concise, generalisable parsing
    images = {
        band_name_s1(prod_path): {
            'path': prod_path
        } for prod_path in prod_paths
    }

    # trusting bands coaligned, use one to generate spatial bounds for all
    try:
        projection, extent = get_geometry(os.path.join(str(scene_dir), images['vh']['path']))
    except:
        projection, extent = get_geometry(os.path.join(str(scene_dir), images['vv']['path']))
        logging.warning('no vh band available')

    # format metadata (i.e. construct hashtable tree for syntax of file interface)
    return {
        'id': str(uuid.uuid5(uuid.NAMESPACE_URL, scene_name)),
        'processing_level': "sac_snap_ard",
        'product_type': "gamma0",
        'creation_dt': str(datetime.today().strftime('%Y-%m-%d %H:%M:%S')),
        'platform': {
            'code': 'SENTINEL_1'
        },
        'instrument': {
            'name': 'SAR'
        },
        'extent': create_metadata_extent(extent, t0, t0),
        'format': {
            'name': 'GeoTiff'
        },
        'grid_spatial': {
            'projection': projection
        },
        'image': {
            'bands': images
        },
        'lineage': {
            'source_datasets': {},
        }

    }


def prepareS1AM(in_scene, chunks=24, s3_bucket='public-eo-data', s3_dir='common_sensing/sentinel_1/', inter_dir='/tmp/data/intermediate/'):
    """
    Prepare a Sentinel-1 scene (L1C or L2A) for indexing in ODC by converting it to COGs.

    :param in_scene: the name of the input Sentinel-1 scene, e.g. "S1A_IW_GRDH_1SDV_20211004T165352_20211004T165417_039025_049FA6_E5F6"
    :param chunks: the number of chunks to use when creating COGs (default is 24)
    :param s3_bucket: the S3 bucket where the scene is located (default is 'public-eo-data')
    :param s3_dir: the directory path within the S3 bucket where the scene is located (default is 'common_sensing/sentinel_1/')
    :param inter_dir: an optional intermediate directory to be used for processing (default is '/tmp/data/intermediate/')
    :return: None
    """

    tmp_inter_dir = inter_dir

    if not in_scene.endswith('.SAFE'):
        in_scene = in_scene + '.SAFE'

    scene_name = in_scene[:32]
    inter_dir = f'{inter_dir}{scene_name}_tmp/'

    cog_dir = os.path.join(inter_dir, scene_name)
    os.makedirs(cog_dir, exist_ok=True)

    down_zip = inter_dir + in_scene.replace('.SAFE','.zip')
    am_dir = down_zip.replace('.zip', 'Orb_Cal_Deb_ML_TF_TC_dB/')

    root.info('{} {} Starting'.format(in_scene, scene_name))

    try:

        # Download scene from ESA
        try:
            s1id = find_s1_uuid(in_scene)
            logging.debug(s1id)
            root.info(f"{in_scene} {scene_name}: Available for download from ESA")
            # download_extract_s1_esa(s1id, inter_dir, down_dir)
            root.info(f"{in_scene} {scene_name}: Downloaded from ESA")
        except Exception as e:
            root.exception(f"{in_scene} {scene_name}: Failed to download from ESA")
            # If there's an error, raise a more specific exception
            raise DownloadError(f"Failed to download {in_scene} from ESA") from e


        # Download external DEMs
        ext_dem_path_list = download_external_dems(in_scene, scene_name, tmp_inter_dir, s3_bucket, root)

        # Process AM
        try:
            root.info(f"{in_scene} {scene_name} Starting AM SNAP processing")        
            # Do AM Processing
            obj = Raw2Ard( chunks=chunks, gpt='/opt/snap/bin/gpt' )
            obj.process(down_zip, am_dir, ext_dem_path_list[0], ext_dem_path_list[1])
        except Exception as e:
            root.exception(e)
            root.exception(f"Processing failed")


        # CONVERT TO COGS TO TEMP COG DIRECTORY**
        try:
            root.info(f"{in_scene} {scene_name} Converting COGs")
            conv_s1scene_cogs(inter_dir, cog_dir, scene_name)
            root.info(f"{in_scene} {scene_name} COGGED")
        except Exception as e:
            root.exception(f"{in_scene} {scene_name} COG conversion FAILED")
            raise Exception('COG Error', e)


        # GENERATE YAML WITHIN TEMP COG DIRECTORY**
        try:
            root.info(f"{in_scene} {scene_name} Creating dataset YAML")
            create_yaml(cog_dir, yaml_prep_s1(cog_dir))
            root.info(f"{in_scene} {scene_name} Created original METADATA")
        except Exception as e:
            root.exception(f"{in_scene} {scene_name} Dataset YAML not created")
            raise Exception('YAML creation error', e)


        # MOVE COG DIRECTORY TO OUTPUT DIRECTORY
        try:
            root.info(f"{in_scene} {scene_name} Uploading to S3 Bucket")
            s3_upload_cogs(glob.glob(os.path.join(cog_dir, '*')), s3_bucket, s3_dir)
            root.info(f"{in_scene} {scene_name} Uploaded to S3 Bucket")
        except Exception as e:
            root.exception(f"{in_scene} {scene_name} Upload to S3 Failed")
            raise Exception('S3  upload error', e)

        # DELETE ANYTHING WITHIN THE TEMP DIRECTORY
        clean_up(inter_dir)

    except Exception as e:
        logging.error(f"could not process {scene_name} {e}")
        # clean_up(inter_dir)


if __name__ == '__main__':
    prepareS1AM('S1A_IW_GRDH_1SDV_20230118T174108_20230118T174131_046841_059DD6_8B3D', s3_dir='fiji/Sentinel_1_dockertest/')
