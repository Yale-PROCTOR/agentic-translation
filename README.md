# Usage

```bash
./translate.py <input tarball> <output directory>
```

(A tarball can be generated using the bundler provided by
<https://github.com/DARPA-TRACTOR-Program/aws-translate>)

## Example

```bash
./translate.py \
  bundles/Public-Tests/B01_synthetic/001_helloworld.tar.gz \
  Test-Corpus/Public-Tests/B01_synthetic/001_helloworld/translated_rust
```

# Current Capabilities

* Test vector generation and translation for single-executable or
  single-shared-library test cases
