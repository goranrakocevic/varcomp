import subprocess
from vcomp import util


def get_callers():
    return {
        "freebayes": call_variant_fb,
        "samtools": call_variant_mp_bcf,
        "platypus": call_variant_platypus,
        "varscan": call_variant_varscan,
        #platypus-asm": call_variant_platypus_asm,
        #"rtg": call_variant_rtg,
        "gatk-hc": call_variant_gatk_hc,
        #"wecall": call_wecall,
        "gatk-ug": call_variant_gatk_ug
        #"wecall": call_wecall
        # "freebayes-mre": call_variant_fb_minrepeatentropy,
    }


def call_variant_platypus_asm(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-platypus.vcf"
    cmd= "python " + conf.get('main', 'platypus_path') + " callVariants --assemble=1 --assembleBadReads=1 --refFile " + orig_genome_path + " --bamFiles " + bam + " --regions " + bed + " -o " + vcfoutput
    subprocess.check_call(cmd, shell=True)
    return util.compress_vcf(vcfoutput, conf)

def call_variant_fb(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-fb.vcf"
    cmd=[conf.get('main', 'freebayes_path'), "-f", orig_genome_path, "-t", bed, "-b", bam, "-v", vcfoutput]
    subprocess.check_output(cmd)
    return util.sort_vcf(vcfoutput, conf)

def call_variant_fb_minrepeatentropy(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-fb.vcf"
    cmd=[conf.get('main', 'freebayes_path'), "-f", orig_genome_path, "--min-repeat-entropy", "1", "-t", bed, "-b", bam, "-v", vcfoutput]
    subprocess.check_output(cmd)
    return util.compress_vcf(vcfoutput, conf)

def call_variant_platypus(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-platypus.vcf"
    cmd= "python " + conf.get('main', 'platypus_path') + " callVariants --refFile " + orig_genome_path + " --bamFiles " + bam + " --regions " + bed + " -o " + vcfoutput
    subprocess.check_call(cmd, shell=True)
    return util.compress_vcf(vcfoutput, conf)

def call_wecall(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-wc.vcf"
    cmd=conf.get('main', 'wecall_path') + " --refFile " + orig_genome_path + " --inputs " + bam + " --regions " + bed + " --output " + vcfoutput
    subprocess.check_call(cmd, shell=True)
    return util.compress_vcf(vcfoutput, conf)

def call_variant_gatk_hc(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-hc.vcf"
    err = open("/dev/null")
    no_et = ""
    try:
        no_et = " -et NO_ET -K " + conf.get('main', 'gatk_no_et')
    except:
        pass
    cmd="java -Xmx1g -Djava.io.tmpdir=. -jar " + conf.get('main', 'gatk_path') + " -T HaplotypeCaller " + no_et + " -R " + orig_genome_path +" -I " + bam + " -L " + bed + " -o " + vcfoutput
    subprocess.check_output(cmd, shell=True, stderr=err)
    err.close()
    return util.compress_vcf(vcfoutput, conf)


def call_variant_gatk_ug(bam, orig_genome_path, bed, conf=None):
    vcfoutput = "output-ug.vcf"
    err = open("/dev/null")
    no_et = ""
    try:
        no_et = " -et NO_ET -K " + conf.get('main', 'gatk_no_et')
    except:
        pass
    cmd="java -Xmx1g -Djava.io.tmpdir=. -jar " + conf.get('main', 'gatk_path') + " -T UnifiedGenotyper -glm BOTH " + no_et + " -R " + orig_genome_path +" -I " + bam + " -L " + bed + " -o " + vcfoutput
    subprocess.check_output(cmd, shell=True, stderr=err)
    err.close()
    return util.compress_vcf(vcfoutput, conf)


def call_variant_rtg(bam, orig_genome_path, bed, conf):
    output_dir = "rtg-output-" + util.randstr()
    vcfoutput = output_dir + "/snps.vcf.gz"
    cmd=["java", "-Djava.io.tmpdir=.", "-jar", conf.get('main', 'rtg_jar'), "snp", "-t", conf.get('main', 'rtg_ref_sdf'), "--bed-regions", bed, "-o", output_dir, bam]
    subprocess.check_output(cmd)
    return vcfoutput

def call_variant_varscan(bam, orig_genome_path, bed, conf):
    pre_output = "varscan." + util.randstr() + ".mpileup"
    vcfoutput = "output-vs." + util.randstr() + ".vcf"
    bedarg = ""
    if bed is not None:
        bedarg = " -l " + bed
    cmd = conf.get('main','samtools_path') + ' mpileup ' + ' -f ' + orig_genome_path + " -o " + pre_output + " " + bedarg + " " + bam
    subprocess.check_call(cmd, shell=True)
    cmd2 = "java -Xmx2g -jar " + conf.get('main', 'varscan_path') + ' mpileup2cns ' + pre_output + ' --variants --output-vcf 1 --output-file ' + vcfoutput
    output = subprocess.check_output(cmd2, shell=True)
    with open(vcfoutput, "w") as fh:
        fh.write(output)
    return util.bgz_tabix(vcfoutput, conf)

def call_variant_mp_bcf(bam, orig_genome_path, bed, conf):
    pre_output = "mpileup." + util.randstr() + ".vcf"
    vcfoutput = "output-mp." + util.randstr() + ".vcf"
    bedarg = ""
    if bed is not None:
        bedarg = " -l " + bed
    cmd = conf.get('main','samtools_path') + ' mpileup ' + ' -f ' + orig_genome_path + " -uv " + " -o " + pre_output + " " + bedarg + " " + bam
    subprocess.check_call(cmd, shell=True)
    cmd2 = conf.get('main', 'bcftools_path') + ' call ' + ' -mv ' + ' -o ' + vcfoutput + " " + pre_output
    subprocess.check_call(cmd2, shell=True)
    return util.bgz_tabix(vcfoutput, conf)



