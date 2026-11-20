# Decoder comparison: results

2640 decoder runs. A read counts only if the returned text is exactly the known content.

## Overall (all conditions together)

| Code type | Decoder | Images | Read correctly | Misread | Nothing | Median ms | p95 ms |
|---|---|---|---|---|---|---|---|
| QR code | eCode pipeline | 176 | 95.5 % | 0.0 % | 4.5 % | 11.6 | 151.8 |
| QR code | zxing-cpp | 176 | 93.8 % | 0.0 % | 6.2 % | 13.4 | 91.9 |
| QR code | pyzbar (ZBar) | 176 | 78.4 % | 0.0 % | 21.6 % | 10.6 | 120.6 |
| QR code | OpenCV QRCodeDetector | 176 | 76.1 % | 0.0 % | 23.9 % | 36.4 | 66.3 |
| QR code | OpenCV QRCodeDetectorAruco | 176 | 67.6 % | 0.0 % | 32.4 % | 21.0 | 84.0 |
| DataMatrix | eCode pipeline | 176 | 100.0 % | 0.0 % | 0.0 % | 11.5 | 76.1 |
| DataMatrix | zxing-cpp | 176 | 100.0 % | 0.0 % | 0.0 % | 12.8 | 63.0 |
| DataMatrix | pylibdmtx | 176 | 93.8 % | 0.0 % | 6.2 % | 56.8 | 1993.3 |
| Code 128 | eCode pipeline | 176 | 81.8 % | 0.0 % | 18.2 % | 17.0 | 336.9 |
| Code 128 | zxing-cpp | 176 | 57.4 % | 0.0 % | 42.6 % | 15.3 | 82.0 |
| Code 128 | pyzbar (ZBar) | 176 | 55.1 % | 0.0 % | 44.9 % | 9.4 | 113.3 |
| EAN-13 | eCode pipeline | 176 | 85.8 % | 1.1 % | 13.1 % | 16.3 | 314.7 |
| EAN-13 | zxing-cpp | 176 | 58.5 % | 1.1 % | 40.3 % | 14.6 | 88.2 |
| EAN-13 | pyzbar (ZBar) | 176 | 73.3 % | 0.0 % | 26.7 % | 9.3 | 116.1 |
| EAN-13 | OpenCV BarcodeDetector | 176 | 65.3 % | 0.0 % | 34.7 % | 10.6 | 13.1 |

## QR code: correct reads (%) per condition

| Condition | eCode pipeline | zxing-cpp | pyzbar | OpenCV QR | OpenCV QR Aruco |
|---|---|---|---|---|---|
| clean | 100 | 100 | 100 | 100 | 100 |
| blur_1.0 | 100 | 100 | 100 | 88 | 12 |
| blur_2.0 | 100 | 62 | 0 | 0 | 0 |
| blur_3.0 | 0 | 0 | 0 | 0 | 0 |
| noise_15 | 100 | 100 | 100 | 100 | 100 |
| noise_30 | 100 | 100 | 100 | 100 | 100 |
| noise_50 | 100 | 100 | 100 | 88 | 62 |
| jpeg_30 | 100 | 100 | 100 | 100 | 100 |
| jpeg_15 | 100 | 100 | 100 | 100 | 100 |
| jpeg_8 | 100 | 100 | 75 | 88 | 75 |
| contrast_0.5 | 100 | 100 | 100 | 100 | 100 |
| contrast_0.25 | 100 | 100 | 100 | 100 | 100 |
| rotate_10 | 100 | 100 | 100 | 100 | 100 |
| rotate_30 | 100 | 100 | 100 | 88 | 88 |
| rotate_45 | 100 | 100 | 100 | 100 | 75 |
| rotate_90 | 100 | 100 | 100 | 100 | 100 |
| perspective | 100 | 100 | 100 | 100 | 88 |
| small_0.5 | 100 | 100 | 88 | 25 | 62 |
| small_0.35 | 100 | 100 | 0 | 0 | 0 |
| inverted | 100 | 100 | 0 | 0 | 0 |
| shading | 100 | 100 | 100 | 100 | 100 |
| poor_scan | 100 | 100 | 62 | 100 | 25 |

## DataMatrix: correct reads (%) per condition

| Condition | eCode pipeline | zxing-cpp | pylibdmtx |
|---|---|---|---|
| clean | 100 | 100 | 100 |
| blur_1.0 | 100 | 100 | 100 |
| blur_2.0 | 100 | 100 | 100 |
| blur_3.0 | 100 | 100 | 100 |
| noise_15 | 100 | 100 | 100 |
| noise_30 | 100 | 100 | 62 |
| noise_50 | 100 | 100 | 25 |
| jpeg_30 | 100 | 100 | 100 |
| jpeg_15 | 100 | 100 | 100 |
| jpeg_8 | 100 | 100 | 100 |
| contrast_0.5 | 100 | 100 | 100 |
| contrast_0.25 | 100 | 100 | 100 |
| rotate_10 | 100 | 100 | 75 |
| rotate_30 | 100 | 100 | 100 |
| rotate_45 | 100 | 100 | 100 |
| rotate_90 | 100 | 100 | 100 |
| perspective | 100 | 100 | 100 |
| small_0.5 | 100 | 100 | 100 |
| small_0.35 | 100 | 100 | 100 |
| inverted | 100 | 100 | 100 |
| shading | 100 | 100 | 100 |
| poor_scan | 100 | 100 | 100 |

## Code 128: correct reads (%) per condition

| Condition | eCode pipeline | zxing-cpp | pyzbar |
|---|---|---|---|
| clean | 100 | 100 | 100 |
| blur_1.0 | 100 | 100 | 100 |
| blur_2.0 | 0 | 0 | 0 |
| blur_3.0 | 0 | 0 | 0 |
| noise_15 | 100 | 100 | 0 |
| noise_30 | 100 | 100 | 0 |
| noise_50 | 100 | 0 | 0 |
| jpeg_30 | 100 | 100 | 100 |
| jpeg_15 | 100 | 100 | 62 |
| jpeg_8 | 100 | 50 | 62 |
| contrast_0.5 | 100 | 100 | 100 |
| contrast_0.25 | 100 | 100 | 100 |
| rotate_10 | 100 | 100 | 100 |
| rotate_30 | 0 | 0 | 0 |
| rotate_45 | 100 | 0 | 0 |
| rotate_90 | 100 | 100 | 100 |
| perspective | 100 | 100 | 100 |
| small_0.5 | 100 | 12 | 88 |
| small_0.35 | 0 | 0 | 0 |
| inverted | 100 | 0 | 0 |
| shading | 100 | 0 | 100 |
| poor_scan | 100 | 100 | 100 |

## EAN-13: correct reads (%) per condition

| Condition | eCode pipeline | zxing-cpp | pyzbar | OpenCV Barcode |
|---|---|---|---|---|
| clean | 100 | 100 | 100 | 50 |
| blur_1.0 | 100 | 100 | 100 | 100 |
| blur_2.0 | 0 | 0 | 0 | 0 |
| blur_3.0 | 0 | 0 | 0 | 0 |
| noise_15 | 100 | 100 | 100 | 100 |
| noise_30 | 100 | 100 | 100 | 100 |
| noise_50 | 100 | 0 | 100 | 100 |
| jpeg_30 | 100 | 100 | 100 | 62 |
| jpeg_15 | 100 | 100 | 100 | 88 |
| jpeg_8 | 100 | 88 | 100 | 100 |
| contrast_0.5 | 100 | 100 | 100 | 50 |
| contrast_0.25 | 100 | 100 | 100 | 50 |
| rotate_10 | 100 | 100 | 100 | 100 |
| rotate_30 | 75 | 0 | 75 | 100 |
| rotate_45 | 100 | 0 | 0 | 100 |
| rotate_90 | 100 | 100 | 100 | 38 |
| perspective | 100 | 100 | 100 | 100 |
| small_0.5 | 100 | 0 | 38 | 50 |
| small_0.35 | 12 | 0 | 0 | 0 |
| inverted | 100 | 0 | 0 | 0 |
| shading | 100 | 0 | 100 | 50 |
| poor_scan | 100 | 100 | 100 | 100 |

## Misreads (wrong content returned)

- eCode pipeline on EAN-13: 2
- zxing-cpp on EAN-13: 2
